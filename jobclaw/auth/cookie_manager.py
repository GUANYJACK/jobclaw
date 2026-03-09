"""Unified cookie loading: config (.env) > persisted file > prompt login.

Provides a single entry point for all cookie needs across scraper and applier layers.
"""

from __future__ import annotations

import logging

from jobclaw.auth.browser_login import load_cookies

logger = logging.getLogger(__name__)

# Maps platform name to the Settings attribute for the cookie value
_PLATFORM_COOKIE_ATTR = {
    "boss": "boss_cookie",
    "linkedin": "linkedin_cookie",
    "jobsdb": "jobsdb_cookie",
}

# Maps platform name to the cookie name + domain used for injection
_PLATFORM_COOKIE_META = {
    "boss": {"name": "wt2", "domain": ".zhipin.com", "path": "/"},
    "linkedin": {"name": "li_at", "domain": ".linkedin.com", "path": "/"},
    "jobsdb": {"name": "JobseekerSessionId", "domain": ".jobsdb.com", "path": "/"},
}


class CookieNotFoundError(Exception):
    """Raised when no cookies are available for a platform."""


async def get_cookies(platform: str, settings: object) -> list[dict]:
    """Load cookies with priority: .env config > persisted file > raise.

    Args:
        platform: Platform name (``boss`` or ``linkedin``).
        settings: Settings instance with cookie attributes.

    Returns:
        List of Playwright-format cookie dicts.

    Raises:
        CookieNotFoundError: If no cookies are available from any source.
    """
    # Priority 1: .env / Settings
    attr = _PLATFORM_COOKIE_ATTR.get(platform)
    if attr:
        env_cookie = getattr(settings, attr, None)
        if env_cookie:
            meta = _PLATFORM_COOKIE_META[platform]
            logger.debug("Using %s cookie from .env config", platform)
            return [
                {
                    "name": meta["name"],
                    "value": env_cookie,
                    "domain": meta["domain"],
                    "path": meta["path"],
                }
            ]

    # Priority 2: Persisted cookie file
    persisted = await load_cookies(platform)
    if persisted:
        logger.debug("Using %s cookie from persisted file", platform)
        return persisted

    # Priority 3: No cookies — tell user to login
    raise CookieNotFoundError(
        f"No cookies found for {platform}. "
        f"Please run: jobclaw login --platform {platform}"
    )


async def inject_cookies(context: object, platform: str, settings: object) -> None:
    """Inject cookies into a Playwright browser context.

    Args:
        context: Playwright BrowserContext.
        platform: Platform name.
        settings: Settings instance.

    Raises:
        CookieNotFoundError: If no cookies are available.
    """
    cookies = await get_cookies(platform, settings)
    await context.add_cookies(cookies)  # type: ignore[union-attr]
    logger.debug("Injected %d cookies for %s", len(cookies), platform)
