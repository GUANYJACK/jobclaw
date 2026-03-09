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
    'input[type="radio"]',  # resume radio buttons
    '[data-automation="resume-select"]',
    '[data-testid="resume-option"]',
]

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
    - Auto-selects the first available resume or uploads one
    - Anti-detection: stealth browser, random delays, realistic UA
    - Captcha detection with notification fallback
    - Apply history to prevent duplicates

    Usage::

        async with JobsDBApplier(settings) as applier:
            result = await applier.apply(job, profile)
    """

    def __init__(
        self,
        settings: Settings,
        *,
        notifier: object | None = None,
        history: ApplyHistory | None = None,
        resume_path: str | None = None,
    ) -> None:
        self._settings = settings
        self._notifier = notifier
        self._history = history or ApplyHistory()
        self._resume_path = resume_path or getattr(settings, "jobsdb_resume_path", None)
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
        """Select the first available resume in the apply form."""
        for sel in _RESUME_SELECT:
            try:
                radios = await page.query_selector_all(sel)
                for radio in radios:
                    if await radio.is_visible():
                        await radio.click()
                        logger.info("Selected resume via %s", sel)
                        return True
            except Exception:
                continue
        return False

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
