"""Command-line interface for JobClaw workflows."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click

from jobclaw.applier.boss import BossApplier
from jobclaw.applier.jobsdb import JobsDBApplier
from jobclaw.auth.browser_login import (
    PLATFORM_CONFIG,
    cookies_valid,
    get_cookie_age_hours,
    interactive_login,
)
from jobclaw.applier.linkedin import LinkedInApplier
from jobclaw.config import get_settings
from jobclaw.matcher.llm_matcher import LLMMatcher
from jobclaw.models import JobSource
from jobclaw.notifier.discord import DiscordNotifier
from jobclaw.notifier.telegram import TelegramNotifier
from jobclaw.profile.loader import load_profile
from jobclaw.scraper.boss import BossScraper
from jobclaw.scraper.jobsdb import JobsDBScraper
from jobclaw.scraper.linkedin import LinkedInScraper


@click.group(help="JobClaw: AI-powered job hunting agent.")
def main() -> None:
    """Root CLI group."""


@main.command("validate-profile")
@click.option(
    "--profile",
    "profile_path",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    required=True,
    help="Path to profile YAML or JSON file.",
)
def validate_profile_command(profile_path: Path) -> None:
    """Validate a profile document against the Profile model."""

    profile = load_profile(profile_path)
    click.echo(f"Profile OK: {profile.name} ({len(profile.skills)} skills)")


@main.command("init-profile")
@click.option(
    "--output", "-o",
    default="profiles/me.yaml",
    show_default=True,
    help="Output path for the generated profile YAML.",
)
def init_profile_command(output: str) -> None:
    """Interactive profile builder — answer questions, AI generates your profile."""
    from jobclaw.profile.builder import interactive_profile_builder
    asyncio.run(interactive_profile_builder(output_path=output))


@main.command("scrape")
@click.option("--platform", type=click.Choice(["boss", "linkedin", "jobsdb", "all"]), default="all")
@click.option("--query", required=True, help="Search query, e.g. 'Python Engineer'.")
@click.option("--location", default=None, help="Optional location filter.")
@click.option("--limit", default=20, show_default=True, type=int)
@click.option("--output", "-o", default=None, type=click.Path(), help="Save results to JSON file.")
def scrape_command(platform: str, query: str, location: str | None, limit: int, output: str | None) -> None:
    """Scrape jobs from selected platforms and print a summary."""

    asyncio.run(_scrape(platform=platform, query=query, location=location, limit=limit, output=output))


@main.command("run")
@click.option("--platform", type=click.Choice(["boss", "linkedin", "jobsdb", "all"]), default="all")
@click.option("--query", required=True, help="Search query, e.g. 'AI Engineer'.")
@click.option("--location", default=None, help="Optional location filter.")
@click.option(
    "--profile",
    "profile_path",
    type=click.Path(path_type=Path, exists=True, dir_okay=False),
    required=True,
)
@click.option("--limit", default=20, show_default=True, type=int)
def run_command(
    platform: str,
    query: str,
    location: str | None,
    profile_path: Path,
    limit: int,
) -> None:
    """Run end-to-end pipeline: scrape -> match -> notify."""

    asyncio.run(
        _run_pipeline(
            platform=platform,
            query=query,
            location=location,
            profile_path=profile_path,
            limit=limit,
        )
    )


@main.command("login")
@click.option(
    "--platform",
    type=click.Choice(["boss", "linkedin", "jobsdb", "all"]),
    default="boss",
    show_default=True,
    help="Job platform to log in to.",
)
@click.option("--timeout", type=int, default=5, show_default=True, help="Login timeout in minutes.")
@click.option("--check", is_flag=True, help="Only check if existing cookies are valid.")
def login_command(platform: str, timeout: int, check: bool) -> None:
    """Interactive browser login to job platforms."""
    platforms = list(PLATFORM_CONFIG.keys()) if platform == "all" else [platform]
    asyncio.run(_login(platforms=platforms, timeout=timeout, check_only=check))


@main.command("login-llm")
@click.option(
    "--provider",
    type=click.Choice(["copilot"]),
    default="copilot",
    show_default=True,
    help="LLM provider to authenticate.",
)
@click.option("--timeout", type=int, default=5, show_default=True, help="Login timeout in minutes.")
@click.option("--check", is_flag=True, help="Check current LLM authentication status.")
def login_llm_command(provider: str, timeout: int, check: bool) -> None:
    """Authenticate with an LLM provider (e.g. GitHub Copilot)."""
    if check:
        asyncio.run(_check_llm_status())
        return
    if provider == "copilot":
        asyncio.run(_login_copilot(timeout))


async def _check_llm_status() -> None:
    """Check all LLM backends and report status."""
    from pathlib import Path
    from jobclaw.config import get_settings
    settings = get_settings()

    click.echo("🔍 LLM Authentication Status\n" + "=" * 40)

    # 1. Claude OAuth
    creds_path = Path(
        settings.claude_credentials_path
        or (Path.home() / ".claude" / ".credentials.json")
    )
    if creds_path.exists():
        from jobclaw.auth.token_refresh import ensure_valid_token
        valid = ensure_valid_token(creds_path)
        status = "✅ Valid" if valid else "⚠️ Expired (refresh failed)"
        click.echo(f"  Claude OAuth: {status}")
        click.echo(f"    Path: {creds_path}")
    else:
        click.echo("  Claude OAuth: ❌ Not configured")
        click.echo(f"    (Looking for: {creds_path})")

    # 2. GitHub Copilot
    from jobclaw.auth.copilot_auth import load_github_token
    gh_token = load_github_token()
    if gh_token:
        click.echo(f"  GitHub Copilot: ✅ Token found (ghu_...{gh_token[-4:]})")
        # Try to exchange for Copilot token
        try:
            import httpx
            resp = httpx.get(
                "https://api.github.com/user",
                headers={"Authorization": f"token {gh_token}", "Accept": "application/json"},
                timeout=10.0,
            )
            if resp.status_code == 200:
                user = resp.json()
                click.echo(f"    GitHub user: {user.get('login', '?')}")
            else:
                click.echo(f"    ⚠️ Token may be invalid (status {resp.status_code})")

            resp2 = httpx.get(
                "https://api.github.com/copilot_internal/v2/token",
                headers={"Authorization": f"token {gh_token}", "Accept": "application/json"},
                timeout=10.0,
            )
            if resp2.status_code == 200:
                click.echo("    Copilot subscription: ✅ Active")
            elif resp2.status_code == 403:
                click.echo("    Copilot subscription: ❌ 403 Forbidden")
                click.echo(f"    Response: {resp2.text[:300]}")
                click.echo("    → This may be an OAuth scope/client_id issue")
                click.echo("    → Check: https://github.com/settings/copilot")
            else:
                click.echo(f"    Copilot subscription: ⚠️ Status {resp2.status_code}")
                click.echo(f"    Response: {resp2.text[:300]}")
        except Exception as e:
            click.echo(f"    ⚠️ Network error: {e}")
    else:
        click.echo("  GitHub Copilot: ❌ Not configured")
        click.echo("    Run: jobclaw login-llm --provider copilot")

    # 3. Anthropic API Key
    if settings.anthropic_api_key:
        masked = settings.anthropic_api_key[:8] + "..." + settings.anthropic_api_key[-4:]
        click.echo(f"  Anthropic API Key: ✅ Set ({masked})")
    else:
        click.echo("  Anthropic API Key: ❌ Not set")

    # 4. OpenAI API Key
    import os
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        masked = openai_key[:8] + "..." + openai_key[-4:]
        click.echo(f"  OpenAI API Key: ✅ Set ({masked})")
    else:
        click.echo("  OpenAI API Key: ❌ Not set")

    click.echo(f"\n{'=' * 40}")
    # Show which backend would be used
    from jobclaw.matcher.llm_matcher import _resolve_llm_backend
    backend, model = _resolve_llm_backend()
    click.echo(f"  → Active backend: {backend} (model: {model})")


async def _login_copilot(timeout: int) -> None:
    """GitHub Copilot device flow login."""
    from jobclaw.auth.copilot_auth import device_flow_login, load_github_token

    existing = load_github_token()
    if existing:
        click.echo("ℹ️  Existing GitHub Copilot token found.")
        if not click.confirm("Re-authenticate?", default=False):
            click.echo("Using existing token.")
            return

    try:
        await device_flow_login(timeout_minutes=timeout)
    except (TimeoutError, RuntimeError) as e:
        click.echo(click.style(f"❌ Copilot login failed: {e}", fg="red"))


async def _login(platforms: list[str], timeout: int, check_only: bool) -> None:
    """Internal async login workflow."""
    for plat in platforms:
        if check_only:
            age = get_cookie_age_hours(plat)
            if age is not None:
                click.echo(f"[{plat}] Cookie file age: {age:.1f} hours")
            else:
                click.echo(f"[{plat}] No saved cookies found.")
                continue

            click.echo(f"[{plat}] Validating cookies...")
            valid = await cookies_valid(plat)
            if valid:
                click.echo(click.style(f"[{plat}] ✅ Cookies are valid!", fg="green"))
            else:
                click.echo(click.style(
                    f"[{plat}] ❌ Cookies expired or invalid. Run: jobclaw login --platform {plat}",
                    fg="red",
                ))
            continue

        # Interactive login
        click.echo(f"[{plat}] Opening browser for login (timeout={timeout}m)...")
        click.echo("Please log in manually. The browser will close automatically on success.")
        try:
            key_cookies = await interactive_login(plat, timeout_minutes=timeout)
            click.echo(click.style(f"[{plat}] ✅ Login successful!", fg="green"))
            click.echo(f"  Key cookies saved: {', '.join(key_cookies.keys())}")
            age = get_cookie_age_hours(plat)
            if age is not None:
                click.echo(f"  Cookie file age: {age:.1f} hours")
        except TimeoutError as e:
            click.echo(click.style(f"[{plat}] ❌ {e}", fg="red"))
        except Exception as e:
            click.echo(click.style(f"[{plat}] ❌ Login failed: {e}", fg="red"))


async def _scrape(platform: str, query: str, location: str | None, limit: int, output: str | None = None) -> None:
    """Internal async scrape workflow."""

    import json as _json

    settings = get_settings()
    scrapers = []
    if platform in {"boss", "all"}:
        scrapers.append(BossScraper(settings))
    if platform in {"linkedin", "all"}:
        scrapers.append(LinkedInScraper(settings))
    if platform in {"jobsdb", "all"}:
        scrapers.append(JobsDBScraper(settings))

    if not scrapers:
        click.echo("No scraper configured for requested platform.")
        return

    all_jobs = []
    for scraper in scrapers:
        async with scraper:
            jobs = await scraper.scrape_jobs(query=query, location=location, limit=limit)
            all_jobs.extend(jobs)
            click.echo(f"{scraper.source.value}: scraped {len(jobs)} job(s)")

    click.echo(f"\nTotal scraped jobs: {len(all_jobs)} | Headless={settings.jobclaw_headless}")

    # Print job details
    if all_jobs:
        click.echo(f"\n{'='*80}")
        for i, job in enumerate(all_jobs, 1):
            salary_str = ""
            if job.salary:
                lo = f"{job.salary.min_annual:,}" if job.salary.min_annual else "?"
                hi = f"{job.salary.max_annual:,}" if job.salary.max_annual else "?"
                salary_str = f" | 💰 {lo}-{hi} {job.salary.currency}"
            click.echo(
                f"\n[{i}] {job.title}\n"
                f"    🏢 {job.company} | 📍 {job.location}{salary_str}\n"
                f"    🔗 {job.url}"
            )
            if job.tags:
                click.echo(f"    🏷️  {', '.join(job.tags)}")
            if job.description:
                desc_preview = job.description[:150].replace('\n', ' ')
                click.echo(f"    📝 {desc_preview}...")
        click.echo(f"\n{'='*80}")

    # Save to JSON if --output specified
    if output and all_jobs:
        data = [job.model_dump(mode="json") for job in all_jobs]
        Path(output).write_text(_json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        click.echo(f"\n💾 Results saved to {output}")


async def _run_pipeline(
    platform: str,
    query: str,
    location: str | None,
    profile_path: Path,
    limit: int,
) -> None:
    """Internal async end-to-end workflow."""

    settings = get_settings()
    profile = load_profile(profile_path)
    matcher = LLMMatcher(model_name=settings.jobclaw_llm_model)

    scrapers = []
    if platform in {"boss", "all"}:
        scrapers.append(BossScraper(settings))
    if platform in {"linkedin", "all"}:
        scrapers.append(LinkedInScraper(settings))
    if platform in {"jobsdb", "all"}:
        scrapers.append(JobsDBScraper(settings))

    jobs = []
    for scraper in scrapers:
        async with scraper:
            jobs.extend(await scraper.scrape_jobs(query=query, location=location, limit=limit))

    if not jobs:
        click.echo("No jobs found.")
        return

    matches = await matcher.batch_match(jobs=jobs, profile=profile)
    ranked_matches = sorted(matches, key=lambda match: match.score, reverse=True)

    top_matches = ranked_matches[: min(5, len(ranked_matches))]
    click.echo(f"Top matches for {profile.name}:")
    for match in top_matches:
        click.echo(f"- {match.job_id}: score={match.score:.2f}")

    boss_applier = BossApplier(settings)
    linkedin_applier = LinkedInApplier(settings)
    jobsdb_applier = JobsDBApplier(settings)

    applications = []
    for job in jobs:
        score = next((item.score for item in top_matches if item.job_id == job.id), 0.0)
        if score < 0.75:
            continue

        if job.source == JobSource.BOSS:
            async with boss_applier:
                applications.append(await boss_applier.apply(job=job, profile=profile))
        elif job.source == JobSource.LINKEDIN:
            async with linkedin_applier:
                applications.append(await linkedin_applier.apply(job=job, profile=profile))
        elif job.source == JobSource.JOBSDB:
            async with jobsdb_applier:
                applications.append(await jobsdb_applier.apply(job=job, profile=profile))

    click.echo(f"Applications attempted: {len(applications)}")

    await _notify_summary(
        settings=settings,
        profile_name=profile.name,
        total_jobs=len(jobs),
        total_matches=len(top_matches),
        total_applications=len(applications),
    )


async def _notify_summary(
    *,
    settings: object,
    profile_name: str,
    total_jobs: int,
    total_matches: int,
    total_applications: int,
) -> None:
    """Send summary notifications to configured channels."""

    summary = (
        f"JobClaw run complete for {profile_name}. "
        f"Jobs={total_jobs}, TopMatches={total_matches}, Applications={total_applications}."
    )

    if getattr(settings, "telegram_bot_token", None) and getattr(settings, "telegram_chat_id", None):
        telegram = TelegramNotifier(
            bot_token=settings.telegram_bot_token,
            chat_id=settings.telegram_chat_id,
        )
        await telegram.send_text(summary)

    if getattr(settings, "discord_webhook_url", None):
        discord = DiscordNotifier(webhook_url=settings.discord_webhook_url)
        await discord.send_text(summary)


if __name__ == "__main__":
    main()
