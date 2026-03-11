"""Interactive profile builder — guided Q&A → LLM → validated YAML."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import yaml

from jobclaw.config import get_settings
from jobclaw.models import Profile, SalaryRange

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Questions — grouped by topic
# ---------------------------------------------------------------------------

QUESTIONS: list[dict] = [
    # Basic info
    {
        "key": "name",
        "question": "你叫什么名字？ / What's your name?",
        "hint": "真名或英文名都行",
    },
    {
        "key": "email",
        "question": "你的邮箱是？ / What's your email?",
        "hint": "用于接收面试通知",
    },
    {
        "key": "experience",
        "question": "你有多少年工作经验？ / How many years of work experience do you have?",
        "hint": "应届生填 0",
    },
    # Skills & Background
    {
        "key": "summary",
        "question": "用几句话介绍一下自己的背景和优势？ / Briefly describe your background and strengths.",
        "hint": "比如：全栈开发3年，擅长 Python 和 AI 应用",
    },
    {
        "key": "skills",
        "question": "你掌握了哪些技能？尽量列全。 / What skills do you have? List as many as you can.",
        "hint": "编程语言、框架、工具都算，比如：Python, React, Docker, AWS",
    },
    # Job preferences
    {
        "key": "desired_roles",
        "question": "你想找什么类型的工作？ / What kind of roles are you looking for?",
        "hint": "比如：后端开发、AI 工程师、数据分析师",
    },
    {
        "key": "locations",
        "question": "你想在哪些城市/地区工作？ / Which cities or regions do you prefer?",
        "hint": "比如：深圳、香港、remote（远程）",
    },
    {
        "key": "remote",
        "question": "你接受远程工作吗？ / Are you open to remote work?",
        "hint": "是/否/都可以",
    },
    {
        "key": "salary",
        "question": "你的期望月薪范围是多少？什么币种？ / What's your expected monthly salary range and currency?",
        "hint": "比如：25000-50000 人民币，或 30000-50000 港币",
    },
    {
        "key": "work_schedule",
        "question": "你对工作时间有什么要求？ / Any work schedule preferences?",
        "hint": "比如：双休、弹性工作、不接受 996",
    },
    {
        "key": "industries",
        "question": "你偏好哪些行业？ / Which industries do you prefer?",
        "hint": "比如：AI、金融、游戏、Web3",
    },
    {
        "key": "deal_breakers",
        "question": "你完全不能接受的条件是什么？ / Any absolute deal-breakers?",
        "hint": "比如：996、大小周、无社保、没有年假",
    },
    {
        "key": "links",
        "question": "你有 GitHub、LinkedIn 或个人网站吗？（可选）/ Any portfolio links? (optional)",
        "hint": "直接贴链接，没有就输入'无'或按回车跳过",
    },
]

# ---------------------------------------------------------------------------
# LLM prompt to convert answers → YAML
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a profile builder assistant. Given a user's Q&A answers about their job preferences, generate a valid YAML profile for the JobClaw job hunting tool.

Output ONLY valid YAML (no markdown fences, no explanation). The YAML must follow this exact schema:

```
name: "string"
email: "string"
years_experience: number

summary: >
  multi-line string

skills:
  - skill1
  - skill2

desired_roles:
  - role1
  - role2

preferences:
  locations:
    - "city1"
    - "remote"
  salary_min: number       # monthly salary, integer
  salary_max: number       # monthly salary, integer
  salary_currency: "CNY"   # or "HKD", "USD", etc.
  work_schedule: "string"
  industries:
    - industry1
  deal_breakers:
    - "string"
```

Rules:
1. salary_min and salary_max must be integers (monthly salary)
2. If user gives annual salary, divide by 12
3. If user mentions currency, set salary_currency accordingly (CNY/HKD/USD/etc.)
4. skills should be normalized — capitalize properly (e.g. "python" → "Python")
5. If a field is empty or user skipped, use sensible defaults or omit optional fields
6. years_experience must be a non-negative number
7. Output valid YAML only — no markdown, no comments, no extra text"""

VALIDATION_PROMPT = """You are a YAML profile validator. The following YAML was generated for a job seeker profile.
Check it against these rules and fix any issues:

1. name: non-empty string
2. email: valid email format (or empty string if not provided)
3. years_experience: non-negative number
4. summary: non-empty meaningful text
5. skills: non-empty list of strings, properly capitalized
6. desired_roles: non-empty list of strings
7. preferences.salary_min: positive integer (monthly), must be <= salary_max
8. preferences.salary_max: positive integer (monthly), must be >= salary_min
9. preferences.salary_currency: valid 3-letter currency code
10. preferences.locations: non-empty list
11. No trailing whitespace issues, no invalid YAML syntax

If everything is correct, return the YAML unchanged.
If there are issues, fix them and return the corrected YAML.

Output ONLY valid YAML — no explanation, no markdown fences."""


def _build_user_prompt(answers: dict[str, str]) -> str:
    """Build the LLM prompt from Q&A answers."""
    lines = ["Here are the user's answers:\n"]
    for q in QUESTIONS:
        answer = answers.get(q["key"], "").strip()
        if answer:
            lines.append(f"Q: {q['question']}")
            lines.append(f"A: {answer}\n")
    return "\n".join(lines)


async def _call_llm(system: str, user: str) -> str:
    """Call the configured LLM and return raw text response."""
    settings = get_settings()

    # Try Claude OAuth first, then API keys
    try:
        from jobclaw.matcher.llm_matcher import _resolve_llm_backend
        backend, model_name = _resolve_llm_backend()
    except Exception:
        backend, model_name = "openai", settings.jobclaw_llm_model

    if backend == "claude-oauth":
        from jobclaw.auth import ensure_valid_token, get_claude_token
        from jobclaw.models.claude_api import ClaudeClient

        creds_path = (
            Path(settings.claude_credentials_path)
            if settings.claude_credentials_path
            else None
        )
        ensure_valid_token(creds_path)
        token = get_claude_token(creds_path)
        client = ClaudeClient(token=token, model=model_name or settings.claude_model)
        return await client.chat(user, system=system)

    # LangChain path
    try:
        from langchain_core.messages import HumanMessage, SystemMessage
    except ImportError:
        from langchain.schema import HumanMessage, SystemMessage  # type: ignore[no-redef]

    try:
        from langchain.chat_models import init_chat_model
    except ImportError:
        from langchain_community.chat_models import init_chat_model  # type: ignore[no-redef]

    if backend == "anthropic":
        llm = init_chat_model(model_name, model_provider="anthropic")
    elif backend == "google":
        llm = init_chat_model(
            model_name or settings.gemini_model,
            model_provider="google_genai",
            google_api_key=settings.google_api_key,
        )
    else:
        llm = init_chat_model(model_name or "gpt-4o-mini")

    response = await llm.ainvoke([
        SystemMessage(content=system),
        HumanMessage(content=user),
    ])
    return response.content


def _clean_yaml_response(text: str) -> str:
    """Strip markdown fences and leading/trailing whitespace."""
    text = text.strip()
    if text.startswith("```"):
        # Remove first line (```yaml or ```)
        lines = text.split("\n")
        lines = lines[1:]
        # Remove last ``` line
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


def _validate_profile_data(data: dict) -> list[str]:
    """Validate parsed YAML data and return list of error messages."""
    errors = []

    if not data.get("name"):
        errors.append("name is missing or empty")

    exp = data.get("years_experience")
    if exp is not None:
        try:
            exp = float(exp)
            if exp < 0:
                errors.append("years_experience must be non-negative")
        except (ValueError, TypeError):
            errors.append(f"years_experience is not a number: {exp}")

    if not data.get("skills") or not isinstance(data.get("skills"), list):
        errors.append("skills must be a non-empty list")

    if not data.get("desired_roles") or not isinstance(data.get("desired_roles"), list):
        errors.append("desired_roles must be a non-empty list")

    prefs = data.get("preferences", {})
    if isinstance(prefs, dict):
        s_min = prefs.get("salary_min")
        s_max = prefs.get("salary_max")
        if s_min is not None and s_max is not None:
            try:
                s_min, s_max = int(s_min), int(s_max)
                if s_min < 0:
                    errors.append("salary_min must be positive")
                if s_max < s_min:
                    errors.append("salary_max must be >= salary_min")
            except (ValueError, TypeError):
                errors.append("salary_min/salary_max must be integers")

        if not prefs.get("locations"):
            errors.append("preferences.locations is missing or empty")

    # Try to construct a Profile to catch pydantic errors
    try:
        _data = dict(data)
        preferences = _data.pop("preferences", {})
        if isinstance(preferences, dict):
            currency = preferences.pop("salary_currency", "CNY")
            if "salary_min" in preferences or "salary_max" in preferences:
                _data["salary_expectation"] = SalaryRange(
                    min_annual=(preferences.get("salary_min", 0) or 0) * 12,
                    max_annual=(preferences.get("salary_max", 0) or 0) * 12,
                    currency=currency,
                )
            if "locations" in preferences:
                _data["preferred_locations"] = preferences["locations"]
            if "remote" in preferences:
                _data["remote_ok"] = preferences["remote"]
        Profile.model_validate(_data)
    except Exception as e:
        errors.append(f"Pydantic validation error: {e}")

    return errors


async def generate_profile_yaml(answers: dict[str, str], max_retries: int = 3) -> str:
    """Generate and validate a profile YAML from Q&A answers.

    Args:
        answers: Dict mapping question key → user's answer text.
        max_retries: Max LLM correction attempts.

    Returns:
        Valid YAML string ready to save to file.

    Raises:
        ValueError: If validation fails after all retries.
    """
    user_prompt = _build_user_prompt(answers)

    # Step 1: Generate YAML from answers
    logger.info("Generating profile YAML from %d answers...", len(answers))
    raw_yaml = await _call_llm(SYSTEM_PROMPT, user_prompt)
    raw_yaml = _clean_yaml_response(raw_yaml)

    for attempt in range(max_retries):
        # Step 2: Parse YAML
        try:
            data = yaml.safe_load(raw_yaml)
        except yaml.YAMLError as e:
            logger.warning("YAML parse error (attempt %d): %s", attempt + 1, e)
            # Ask LLM to fix
            fix_prompt = f"The following YAML has syntax errors:\n\n{raw_yaml}\n\nError: {e}\n\nFix the YAML and return only valid YAML."
            raw_yaml = await _call_llm(VALIDATION_PROMPT, fix_prompt)
            raw_yaml = _clean_yaml_response(raw_yaml)
            continue

        if not isinstance(data, dict):
            logger.warning("YAML didn't produce a dict (attempt %d)", attempt + 1)
            raw_yaml = await _call_llm(SYSTEM_PROMPT, user_prompt)
            raw_yaml = _clean_yaml_response(raw_yaml)
            continue

        # Step 3: Validate
        errors = _validate_profile_data(data)
        if not errors:
            logger.info("Profile YAML validated successfully")
            return raw_yaml

        # Step 4: Ask LLM to correct
        logger.warning("Validation errors (attempt %d): %s", attempt + 1, errors)
        fix_prompt = (
            f"The following profile YAML has these validation errors:\n\n"
            f"Errors:\n" + "\n".join(f"- {e}" for e in errors) +
            f"\n\nOriginal YAML:\n{raw_yaml}\n\n"
            f"Original user answers:\n{user_prompt}\n\n"
            f"Fix ALL errors and return corrected YAML only."
        )
        raw_yaml = await _call_llm(VALIDATION_PROMPT, fix_prompt)
        raw_yaml = _clean_yaml_response(raw_yaml)

    # Final attempt — try to parse whatever we have
    try:
        data = yaml.safe_load(raw_yaml)
        if isinstance(data, dict):
            errors = _validate_profile_data(data)
            if not errors:
                return raw_yaml
    except Exception:
        pass

    raise ValueError(
        f"Failed to generate valid profile YAML after {max_retries} attempts. "
        f"Last errors: {errors}"
    )


async def interactive_profile_builder(output_path: str = "profiles/me.yaml") -> Path:
    """Run the interactive Q&A profile builder.

    Asks questions via CLI input, sends answers to LLM, validates,
    and saves the result.

    Args:
        output_path: Where to save the generated YAML.

    Returns:
        Path to the saved profile file.
    """
    import click

    click.echo("\n🦀 JobClaw Profile Builder")
    click.echo("=" * 50)
    click.echo("回答以下问题，我会帮你生成求职画像。")
    click.echo("Answer the questions below and I'll generate your job profile.\n")

    answers: dict[str, str] = {}

    for q in QUESTIONS:
        click.echo(click.style(f"❓ {q['question']}", fg="cyan"))
        if q.get("hint"):
            click.echo(click.style(f"   💡 {q['hint']}", fg="bright_black"))

        answer = click.prompt("   →", default="", show_default=False)
        if answer.strip():
            answers[q["key"]] = answer.strip()
        click.echo()

    if not answers:
        raise click.Abort("No answers provided.")

    click.echo("\n⏳ 正在用 AI 生成你的求职画像... / Generating your profile with AI...\n")

    # Generate YAML
    profile_yaml = await generate_profile_yaml(answers)

    # Show preview
    click.echo(click.style("📄 Generated Profile:", fg="green"))
    click.echo("-" * 50)
    click.echo(profile_yaml)
    click.echo("-" * 50)

    # Confirm
    if not click.confirm("\n✅ 看起来对吗？保存这个画像？ / Does this look correct? Save it?", default=True):
        click.echo("❌ Cancelled. You can run this again with: jobclaw init-profile")
        raise click.Abort()

    # Save
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(profile_yaml, encoding="utf-8")
    click.echo(click.style(f"\n💾 Profile saved to {out}", fg="green"))
    click.echo("Now run: jobclaw run --profile " + str(out) + ' --query "your job query"')

    return out
