"""Interactive browser login for job platforms.

Opens a headed browser, lets the user log in manually, then extracts
and persists cookies for future use by scraper / applier layers.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import time
from pathlib import Path

from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

COOKIE_DIR = Path.home() / ".jobclaw" / "cookies"

PLATFORM_CONFIG: dict[str, dict] = {
    "boss": {
        "login_url": "https://www.zhipin.com/web/user/?ka=header-login",
        "success_indicator": "/web/geek/job",
        "success_selectors": [".user-nav", ".nav-figure"],
        "domain": ".zhipin.com",
        "key_cookies": ["wt2", "wbg", "wd_guid"],
        "check_url": "https://www.zhipin.com/web/geek/job",
        "check_redirect_pattern": "/web/user",
    },
    "linkedin": {
        "login_url": "https://www.linkedin.com/login",
        "success_indicator": "/feed",
        "success_selectors": [".global-nav", "#global-nav"],
        "domain": ".linkedin.com",
        "key_cookies": ["li_at", "JSESSIONID"],
        "check_url": "https://www.linkedin.com/feed/",
        "check_redirect_pattern": "/login",
    },
    "jobsdb": {
        "login_url": "https://hk.jobsdb.com/login",
        "success_indicator": "/profile",
        "success_selectors": [".user-menu", "[data-automation='headerProfile']", ".logged-in"],
        "domain": ".jobsdb.com",
        "key_cookies": ["JobseekerSessionId", "sol"],
        "check_url": "https://hk.jobsdb.com/profile/",
        "check_redirect_pattern": "/login",
    },
}


async def interactive_login(platform: str, timeout_minutes: int = 5) -> dict:
    """Open a headed browser for manual login, then extract and persist cookies.

    Args:
        platform: One of the keys in PLATFORM_CONFIG.
        timeout_minutes: How long to wait before giving up.

    Returns:
        Dict mapping cookie name -> value for the key cookies.

    Raises:
        TimeoutError: If login is not detected within the timeout.
        ValueError: If platform is not supported.
    """
    if platform not in PLATFORM_CONFIG:
        raise ValueError(f"Unsupported platform: {platform}")

    config = PLATFORM_CONFIG[platform]
    deadline = time.monotonic() + timeout_minutes * 60

    async with async_playwright() as pw:
        # Use persistent context with user data dir to appear as a real browser.
        # This avoids "unsafe browser" detection by Google OAuth / JobsDB.
        user_data_dir = str(COOKIE_DIR.parent / "browser_profiles" / platform)
        Path(user_data_dir).mkdir(parents=True, exist_ok=True)

        context = await pw.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,
            channel="chrome",  # Use system Chrome instead of bundled Chromium
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--no-first-run",
                "--no-default-browser-check",
            ],
            ignore_default_args=["--enable-automation"],
            viewport={"width": 1280, "height": 900},
            locale="en-HK",
            timezone_id="Asia/Hong_Kong",
        )

        # Remove webdriver flag
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            delete navigator.__proto__.webdriver;
        """)

        page = context.pages[0] if context.pages else await context.new_page()

        logger.info("Navigating to %s login page: %s", platform, config["login_url"])
        try:
            await page.goto(config["login_url"], wait_until="domcontentloaded", timeout=30_000)
        except Exception as e:
            logger.error("Failed to load login page: %s", e)
            await context.close()
            raise

        logger.info("Waiting for manual login (timeout=%dm)...", timeout_minutes)

        login_detected = False
        while time.monotonic() < deadline:
            try:
                # Check if browser was closed by user
                if page.is_closed():
                    break

                # Check 1: URL contains success indicator
                current_url = page.url
                if config["success_indicator"] in current_url:
                    login_detected = True
                    break

                # Check 2: Page has success selectors
                for selector in config["success_selectors"]:
                    try:
                        el = await page.query_selector(selector)
                        if el and await el.is_visible():
                            login_detected = True
                            break
                    except Exception:
                        continue

                if login_detected:
                    break

                await page.wait_for_timeout(1500)

            except Exception as e:
                # Browser may have been closed
                logger.debug("Poll error (browser closed?): %s", e)
                break

        if not login_detected:
            try:
                await context.close()
            except Exception:
                pass
            raise TimeoutError(
                f"Login not detected within {timeout_minutes} minutes. "
                f"Please try again with `jobclaw login --platform {platform}`."
            )

        # Extract cookies
        all_cookies = await context.cookies()
        _save_cookies(platform, all_cookies)

        # Build key cookie dict
        key_names = set(config["key_cookies"])
        key_cookies = {
            c["name"]: c["value"]
            for c in all_cookies
            if c["name"] in key_names
        }

        logger.info(
            "Login successful for %s. Saved %d cookies (%d key cookies).",
            platform, len(all_cookies), len(key_cookies),
        )

        await context.close()

    return key_cookies


def _save_cookies(platform: str, cookies: list[dict]) -> Path:
    """Save cookies to ~/.jobclaw/cookies/{platform}.json with 0600 permissions."""
    COOKIE_DIR.mkdir(parents=True, exist_ok=True)
    cookie_file = COOKIE_DIR / f"{platform}.json"

    # Add saved_at timestamp for expiry tracking
    data = {
        "saved_at": time.time(),
        "cookies": cookies,
    }
    cookie_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # Set file permissions to 600 (owner read/write only)
    try:
        os.chmod(cookie_file, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        logger.warning("Could not set cookie file permissions to 600")

    logger.info("Cookies saved to %s", cookie_file)
    return cookie_file


async def load_cookies(platform: str) -> list[dict] | None:
    """Load persisted cookies from ~/.jobclaw/cookies/{platform}.json.

    Returns:
        List of Playwright cookie dicts, or None if file doesn't exist.
    """
    cookie_file = COOKIE_DIR / f"{platform}.json"
    if not cookie_file.exists():
        return None

    try:
        data = json.loads(cookie_file.read_text(encoding="utf-8"))
        cookies = data.get("cookies", data)  # support both old (list) and new (dict) format
        if isinstance(cookies, list):
            return cookies
        return None
    except (json.JSONDecodeError, KeyError) as e:
        logger.warning("Failed to load cookies from %s: %s", cookie_file, e)
        return None


def get_cookie_age_hours(platform: str) -> float | None:
    """Return the age of the saved cookie file in hours, or None if not found."""
    cookie_file = COOKIE_DIR / f"{platform}.json"
    if not cookie_file.exists():
        return None
    try:
        data = json.loads(cookie_file.read_text(encoding="utf-8"))
        saved_at = data.get("saved_at")
        if saved_at:
            return (time.time() - saved_at) / 3600
    except Exception:
        pass
    return None


async def cookies_valid(platform: str) -> bool:
    """Check if saved cookies are still valid by visiting a protected page headlessly.

    Returns True if the page loads without redirecting to login.
    """
    if platform not in PLATFORM_CONFIG:
        return False

    cookies = await load_cookies(platform)
    if not cookies:
        return False

    config = PLATFORM_CONFIG[platform]
    check_url = config.get("check_url")
    redirect_pattern = config.get("check_redirect_pattern")

    if not check_url or not redirect_pattern:
        # Can't validate without check config — assume valid if cookies exist
        return True

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context()
            await context.add_cookies(cookies)
            page = await context.new_page()

            await page.goto(check_url, wait_until="domcontentloaded", timeout=15_000)
            current_url = page.url

            await browser.close()

            # If redirected to login page, cookies are invalid
            if redirect_pattern in current_url:
                logger.info("Cookies for %s are expired (redirected to login)", platform)
                return False

            logger.info("Cookies for %s are valid", platform)
            return True

    except Exception as e:
        logger.warning("Cookie validation failed for %s: %s", platform, e)
        return False
