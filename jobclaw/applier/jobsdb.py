"""JobsDB auto-apply adapter — resume upload and quick apply flow."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import datetime, timezone
from typing import Self

from playwright.async_api import Browser, Page, Playwright, async_playwright

from jobclaw.applier.base import BaseApplier
from jobclaw.applier.captcha import detect_captcha, notify_captcha
from jobclaw.applier.history import ApplyHistory
from jobclaw.config import Settings
from jobclaw.models import Application, ApplicationStatus, Job, JobSource, Profile

logger = logging.getLogger(__name__)

# Selectors for JobsDB apply flow
_BTN_QUICK_APPLY = [
    'button[data-automation="job-detail-apply"]',
    'a[data-automation="job-detail-apply"]',
    'button:has-text("Quick apply")',
    'button:has-text("Apply now")',
    'a:has-text("Quick apply")',
    'a:has-text("Apply now")',
    'button:has-text("立即申請")',
    'button:has-text("快速申請")',
]

_RESUME_SELECT = [
    '[data-testid="resume-method-change"]',   # radio: use existing resume
    '[data-testid="resume-method-upload"]',    # radio: upload new file
    '[data-testid="resume-method-none"]',      # radio: no resume
]

_RESUME_DROPDOWN = '[data-testid="resumeSelectInput"] select[data-testid="select-input"]'

_RESUME_UPLOAD = [
    'input[type="file"]',
    '[data-automation="resume-upload"]',
]

_BTN_SUBMIT = [
    'button[data-automation="apply-submit"]',
    'button[type="submit"]:has-text("Submit")',
    'button[type="submit"]:has-text("Apply")',
    'button:has-text("Submit application")',
    'button:has-text("提交申請")',
]

_APPLIED_INDICATORS = [
    "Application submitted",
    "已申請",
    "Applied",
    "You have already applied",
]

# Anti-detection user agents
_USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
]


class JobsDBApplier(BaseApplier):
    """Auto-apply to jobs on JobsDB via the Quick Apply flow.

    Features:
    - Only applies to Quick Apply jobs (external redirects are skipped)
    - Fetches user's resume list from JobsDB and lets them choose
    - Anti-detection: stealth browser, random delays, realistic UA
    - Captcha detection with notification fallback
    - Apply history to prevent duplicates

    Usage::

        async with JobsDBApplier(settings) as applier:
            # Let user choose resume first
            await applier.select_resume_interactive()
            result = await applier.apply(job, profile)
    """

    def __init__(
        self,
        settings: Settings,
        *,
        notifier: object | None = None,
        history: ApplyHistory | None = None,
        resume_path: str | None = None,
        resume_index: int | None = None,
    ) -> None:
        self._settings = settings
        self._notifier = notifier
        self._history = history or ApplyHistory()
        self._resume_path = resume_path or getattr(settings, "jobsdb_resume_path", None)
        self._resume_index = resume_index  # 0-based index of selected resume
        self._resume_value: str | None = None  # UUID of selected resume
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    async def __aenter__(self) -> Self:
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=getattr(self._settings, "jobclaw_headless", True),
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )
        logger.info("JobsDBApplier browser launched")
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        logger.info("JobsDBApplier browser closed")

    async def apply(self, job: Job, profile: Profile) -> Application:
        """Submit a quick apply on JobsDB.

        Returns Application with status:
          - SUBMITTED — application sent
          - FAILED — unrecoverable error
          - CAPTCHA_BLOCKED — captcha detected
        """
        t0 = time.monotonic()
        logger.info("JobsDB apply START: %s @ %s [%s]", job.title, job.company, job.url)

        # Pre-flight
        if self._history.is_applied(job.id):
            logger.info("Skipped (already applied): %s", job.id)
            return self._make_app(job, ApplicationStatus.SUBMITTED, extra={"reason": "already_applied"})

        # Only apply to Quick Apply jobs
        if job.metadata.get("quick_apply") is False:
            logger.info("Skipped (no Quick Apply): %s @ %s", job.title, job.company)
            return self._make_app(job, ApplicationStatus.FAILED, extra={"reason": "no_quick_apply"})

        daily_limit = getattr(self._settings, "jobsdb_daily_limit", 50)
        if self._history.today_count() >= daily_limit:
            logger.warning("Daily limit reached (%d)", daily_limit)
            return self._make_app(job, ApplicationStatus.FAILED, extra={"reason": "daily_limit"})

        if not self._browser:
            raise RuntimeError("JobsDBApplier not initialised — use 'async with'.")

        # Create stealth context
        context = await self._browser.new_context(
            user_agent=random.choice(_USER_AGENTS),
            viewport={"width": random.randint(1280, 1920), "height": random.randint(800, 1080)},
            locale="en-HK",
            timezone_id="Asia/Hong_Kong",
        )

        # Anti-detection init script
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = { runtime: {} };
        """)

        # Inject cookies
        try:
            from jobclaw.auth.cookie_manager import inject_cookies
            await inject_cookies(context, "jobsdb", self._settings)
        except Exception as e:
            logger.warning("JobsDB cookie injection failed: %s", e)

        page = await context.new_page()

        try:
            return await self._do_apply(page, job, profile, t0)
        except Exception as exc:
            logger.exception("Unexpected error during JobsDB apply: %s", exc)
            return self._make_app(
                job, ApplicationStatus.FAILED,
                extra={"reason": "unexpected_error", "error": str(exc)},
            )
        finally:
            await context.close()

    async def _do_apply(
        self, page: Page, job: Job, profile: Profile, t0: float,
    ) -> Application:
        """Core apply flow."""

        # 1. Navigate to job page
        logger.info("Navigating to %s", job.url)
        await page.goto(str(job.url), wait_until="domcontentloaded", timeout=45_000)
        await self._human_delay(1.0, 2.5)

        # 2. Captcha check
        if await detect_captcha(page):
            if self._notifier:
                await notify_captcha(self._notifier, str(job.url))
            return self._make_app(job, ApplicationStatus.CAPTCHA_BLOCKED, extra={"reason": "captcha"})

        # 3. Check if already applied
        body_text = await page.inner_text("body")
        for indicator in _APPLIED_INDICATORS:
            if indicator.lower() in body_text.lower():
                logger.info("Already applied: %s", job.id)
                self._history.mark_applied(job.id, "submitted")
                return self._make_app(
                    job, ApplicationStatus.SUBMITTED, extra={"reason": "already_applied"}
                )

        # 4. Find and click Quick Apply / Apply Now
        apply_btn = await self._find_element(page, _BTN_QUICK_APPLY)
        if not apply_btn:
            logger.error("Cannot find apply button for %s", job.url)
            return self._make_app(job, ApplicationStatus.FAILED, extra={"reason": "button_not_found"})

        logger.info("Clicking apply button")
        await apply_btn.click()
        await self._human_delay(2.0, 4.0)

        # 5. Post-click captcha check
        if await detect_captcha(page):
            if self._notifier:
                await notify_captcha(self._notifier, str(job.url))
            return self._make_app(job, ApplicationStatus.CAPTCHA_BLOCKED, extra={"reason": "captcha"})

        # 6. Handle resume selection — select first available resume
        resume_selected = await self._select_resume(page)
        if not resume_selected and self._resume_path:
            # Try uploading resume file
            await self._upload_resume(page)

        await self._human_delay(1.0, 2.0)

        # 7. Fill optional fields (cover letter, etc.) — skip for now
        # JobsDB quick apply usually only needs resume selection

        # 8. Submit
        submit_btn = await self._find_element(page, _BTN_SUBMIT)
        if submit_btn:
            logger.info("Clicking submit")
            await submit_btn.click()
            await self._human_delay(2.0, 4.0)
        else:
            logger.warning("Submit button not found — application may have auto-submitted")

        # 9. Verify
        if await detect_captcha(page):
            if self._notifier:
                await notify_captcha(self._notifier, str(job.url))
            return self._make_app(job, ApplicationStatus.CAPTCHA_BLOCKED, extra={"reason": "captcha"})

        # Check for success indicators
        try:
            await page.wait_for_selector(
                ':text("submitted"), :text("success"), :text("已申請")',
                timeout=5_000,
            )
            logger.info("Application success indicator found")
        except Exception:
            logger.debug("No explicit success indicator — assuming submitted")

        # Mark in history
        self._history.mark_applied(job.id, "submitted")
        elapsed = time.monotonic() - t0
        logger.info("JobsDB apply SUCCESS: %s @ %s (%.1fs)", job.title, job.company, elapsed)

        # Inter-apply delay
        delay_min = getattr(self._settings, "jobsdb_apply_delay_min", 5.0)
        delay_max = getattr(self._settings, "jobsdb_apply_delay_max", 12.0)
        delay = random.uniform(delay_min, delay_max)
        logger.debug("Waiting %.1fs before next apply", delay)
        await asyncio.sleep(delay)

        return self._make_app(
            job, ApplicationStatus.SUBMITTED,
            extra={"response_time": round(elapsed, 2)},
        )

    async def _select_resume(self, page: Page) -> bool:
        """Select a resume in the apply form.

        Clicks 'resume-method-change' radio, then picks a resume from the
        <select> dropdown by stored resume_index or value.
        """
        # 1. Click the "use existing resume" radio
        change_radio = await page.query_selector('[data-testid="resume-method-change"]')
        if not change_radio:
            logger.warning("resume-method-change radio not found")
            return False
        await change_radio.click()
        await self._human_delay(0.5, 1.0)

        # 2. Pick from dropdown
        select_el = await page.query_selector(_RESUME_DROPDOWN)
        if not select_el:
            logger.warning("Resume select dropdown not found")
            return False

        # Get available options (skip the disabled placeholder)
        options = await select_el.query_selector_all('option:not([disabled])')
        if not options:
            logger.warning("No resume options in dropdown")
            return False

        # Use stored value or index
        if self._resume_value:
            await select_el.select_option(value=self._resume_value)
            logger.info("Selected resume by value: %s", self._resume_value)
        else:
            idx = self._resume_index if self._resume_index is not None else 0
            idx = min(idx, len(options) - 1)
            value = await options[idx].get_attribute("value")
            await select_el.select_option(value=value)
            logger.info("Selected resume #%d", idx + 1)

        return True

    async def fetch_resume_list(self, apply_page_url: str | None = None) -> list[dict]:
        """Fetch the list of resumes from the user's JobsDB account.

        Opens an apply page (needs login cookies) to read the resume
        <select> dropdown options.

        Args:
            apply_page_url: A specific /apply URL. If None, searches for
                a Quick Apply job to open.

        Returns:
            List of dicts: {index, name, value}.
        """
        if not self._browser:
            raise RuntimeError("JobsDBApplier not initialised — use 'async with'.")

        context = await self._browser.new_context(
            user_agent=random.choice(_USER_AGENTS),
            viewport={"width": 1440, "height": 900},
            locale="en-HK",
            timezone_id="Asia/Hong_Kong",
        )
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = { runtime: {} };
        """)

        try:
            from jobclaw.auth.cookie_manager import inject_cookies
            await inject_cookies(context, "jobsdb", self._settings)
        except Exception as e:
            logger.warning("Cookie injection failed: %s", e)

        page = await context.new_page()
        resumes: list[dict] = []

        try:
            if apply_page_url and "/apply" in apply_page_url:
                url = apply_page_url
            else:
                # Find a Quick Apply job to open its apply page
                url = await self._find_quick_apply_url(page)
                if not url:
                    logger.error("Could not find a Quick Apply job to fetch resumes")
                    return []

            logger.info("Opening apply page: %s", url)
            await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            await self._human_delay(2.0, 4.0)

            # Click "use existing resume" radio to reveal dropdown
            change_radio = await page.query_selector('[data-testid="resume-method-change"]')
            if change_radio:
                await change_radio.click()
                await self._human_delay(0.5, 1.0)

            # Read dropdown options
            select_el = await page.query_selector(_RESUME_DROPDOWN)
            if not select_el:
                logger.warning("Resume dropdown not found on apply page")
                return []

            options = await select_el.query_selector_all('option:not([disabled])')
            for i, opt in enumerate(options):
                name = (await opt.inner_text()).strip()
                value = await opt.get_attribute("value") or ""
                if name and value:
                    resumes.append({"index": i, "name": name, "value": value})

        except Exception as e:
            logger.error("Failed to fetch resume list: %s", e)
        finally:
            await context.close()

        return resumes

    async def _find_quick_apply_url(self, page: Page) -> str | None:
        """Search JobsDB and find the apply URL of the first Quick Apply job."""
        await page.goto(
            "https://hk.jobsdb.com/jobs?keywords=data",
            wait_until="domcontentloaded",
            timeout=45_000,
        )
        await self._human_delay(2.0, 3.0)

        # Look for a job card with Quick Apply
        cards = await page.query_selector_all(
            'article[data-testid="job-card"], [data-automation="jobListing"]'
        )
        for card in cards[:10]:
            try:
                card_text = await card.inner_text()
                if "quick apply" in card_text.lower() or "快速申請" in card_text:
                    link = await card.query_selector('a[data-automation="jobTitle"], h3 a')
                    if link:
                        href = await link.get_attribute("href") or ""
                        if href.startswith("/"):
                            href = f"https://hk.jobsdb.com{href}"
                        # Extract job ID and build apply URL
                        import re
                        m = re.search(r"/job/(\d+)", href)
                        if m:
                            return f"https://hk.jobsdb.com/job/{m.group(1)}/apply"
            except Exception:
                continue
        return None

    async def select_resume_interactive(self, apply_page_url: str | None = None) -> bool:
        """Interactive CLI flow: fetch resumes and let user pick one.

        Returns:
            True if a resume was selected, False if skipped/failed.
        """
        import click

        click.echo("\n📄 Fetching your JobsDB resume list...")
        resumes = await self.fetch_resume_list(apply_page_url)

        if not resumes:
            click.echo("  ⚠️ No resumes found on your account.")
            click.echo("  Will try to upload from local file if configured.")
            return False

        click.echo(f"\n  Found {len(resumes)} resume(s):\n")
        for r in resumes:
            click.echo(f"  [{r['index'] + 1}] {r['name']}")

        choice = click.prompt(
            "\n  Select resume number",
            type=int,
            default=1,
            show_default=True,
        )

        idx = choice - 1
        if 0 <= idx < len(resumes):
            self._resume_index = idx
            self._resume_value = resumes[idx]["value"]
            click.echo(click.style(f"  ✅ Selected: {resumes[idx]['name']}", fg="green"))
            return True
        else:
            click.echo("  Invalid choice, using first resume.")
            self._resume_index = 0
            self._resume_value = resumes[0]["value"]
            return True

    async def _upload_resume(self, page: Page) -> bool:
        """Upload a resume file if file input is available."""
        if not self._resume_path:
            return False

        for sel in _RESUME_UPLOAD:
            try:
                file_input = await page.query_selector(sel)
                if file_input:
                    await file_input.set_input_files(self._resume_path)
                    logger.info("Uploaded resume: %s", self._resume_path)
                    await self._human_delay(1.0, 2.0)
                    return True
            except Exception as e:
                logger.warning("Resume upload failed via %s: %s", sel, e)
                continue
        return False

    @staticmethod
    async def _find_element(page: Page, selectors: list[str]):
        """Try multiple selectors and return the first visible match."""
        for sel in selectors:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    return el
            except Exception:
                continue
        return None

    @staticmethod
    async def _human_delay(lo: float = 0.5, hi: float = 1.5) -> None:
        await asyncio.sleep(random.uniform(lo, hi))

    @staticmethod
    def _make_app(
        job: Job, status: ApplicationStatus, *, extra: dict | None = None,
    ) -> Application:
        return Application(
            job_id=job.id,
            source=JobSource.JOBSDB,
            status=status,
            message=f"{job.title} @ {job.company}",
            applied_at=datetime.now(timezone.utc) if status == ApplicationStatus.SUBMITTED else None,
            extra=extra or {},
        )
