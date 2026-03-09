"""JobsDB (jobsdb.com) scraper using Playwright with anti-detection."""

from __future__ import annotations

import logging
import random
from typing import Self

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from jobclaw.models import Job, JobSource, SalaryRange
from jobclaw.scraper.base import BaseScraper

logger = logging.getLogger(__name__)

# JobsDB search URL (Hong Kong site)
_SEARCH_URL = "https://hk.jobsdb.com/jobs-in-information-communication-technology"

# Anti-detection: realistic user agents
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
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) "
        "Gecko/20100101 Firefox/126.0"
    ),
]


class JobsDBScraper(BaseScraper):
    """Scrape job listings from JobsDB (hk.jobsdb.com).

    Implements anti-detection measures:
    - Randomized user agents
    - Stealth browser context (disables webdriver flag)
    - Human-like scroll and delay patterns
    - Randomized viewport sizes
    """

    source = JobSource.JOBSDB

    def __init__(self, settings: object) -> None:
        self._settings = settings
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
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def _create_stealth_context(self) -> BrowserContext:
        """Create a browser context with anti-detection measures."""
        if not self._browser:
            raise RuntimeError("Browser not initialized.")

        viewport_w = random.randint(1280, 1920)
        viewport_h = random.randint(800, 1080)

        context = await self._browser.new_context(
            user_agent=random.choice(_USER_AGENTS),
            viewport={"width": viewport_w, "height": viewport_h},
            locale="en-HK",
            timezone_id="Asia/Hong_Kong",
        )

        # Remove webdriver flag
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            // Override chrome.runtime to look like a real browser
            window.chrome = { runtime: {} };
            // Override permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) =>
                parameters.name === 'notifications'
                    ? Promise.resolve({ state: Notification.permission })
                    : originalQuery(parameters);
        """)

        return context

    async def scrape_jobs(
        self,
        query: str,
        location: str | None = None,
        limit: int = 20,
    ) -> list[Job]:
        """Scrape JobsDB for jobs matching query.

        Args:
            query: Search keywords (e.g. "Python Engineer").
            location: Optional location filter (e.g. "Hong Kong").
            limit: Maximum number of jobs to return.
        """
        if not self._browser:
            raise RuntimeError("Scraper not initialized. Use 'async with' context.")

        context = await self._create_stealth_context()

        # Inject cookies if available
        try:
            from jobclaw.auth.cookie_manager import inject_cookies
            await inject_cookies(context, "jobsdb", self._settings)
        except Exception as e:
            logger.debug("JobsDB cookie injection skipped: %s", e)

        page = await context.new_page()
        jobs: list[Job] = []

        try:
            # Build search URL
            search_url = f"https://hk.jobsdb.com/jobs?keywords={query}"
            if location:
                search_url += f"&where={location}"

            logger.info("JobsDB: navigating to %s", search_url)
            await page.goto(search_url, wait_until="domcontentloaded", timeout=45_000)

            # Wait for job cards to appear
            await page.wait_for_selector(
                'article[data-testid="job-card"], [data-automation="jobListing"]',
                timeout=15_000,
            )

            # Human-like scroll to load more results
            await self._human_scroll(page, scroll_count=min(limit // 10 + 1, 5))

            # Parse job cards
            cards = await page.query_selector_all(
                'article[data-testid="job-card"], [data-automation="jobListing"]'
            )

            for card in cards[:limit]:
                try:
                    job = await self._parse_card(card, page, location)
                    if job:
                        jobs.append(job)
                except Exception as e:
                    logger.warning("Failed to parse JobsDB card: %s", e)
                    continue

            # Fetch full job descriptions from detail pages
            for i, job in enumerate(jobs):
                try:
                    detail = await self._fetch_job_detail(context, str(job.url))
                    if detail:
                        job.description = detail
                        logger.info("Fetched detail %d/%d: %s", i + 1, len(jobs), job.title)
                    await self._human_delay(1.0, 2.5)
                except Exception as e:
                    logger.warning("Failed to fetch detail for %s: %s", job.url, e)

        except Exception as e:
            logger.error("JobsDB scrape failed: %s", e)
            # Try fallback: API-based scraping
            try:
                api_jobs = await self._scrape_via_api(page, query, location, limit)
                jobs.extend(api_jobs)
            except Exception as api_err:
                logger.error("JobsDB API fallback also failed: %s", api_err)
        finally:
            await context.close()

        logger.info("JobsDB: scraped %d jobs for query '%s'", len(jobs), query)
        return jobs

    async def _parse_card(
        self, card: object, page: Page, location: str | None
    ) -> Job | None:
        """Parse a single job card element into a Job object."""
        # Title
        title_el = await card.query_selector(
            'a[data-automation="jobTitle"], h3 a, [data-testid="job-card-title"] a'
        )
        if not title_el:
            return None

        title = (await title_el.inner_text()).strip()
        href = await title_el.get_attribute("href") or ""

        # Company
        company_el = await card.query_selector(
            'a[data-automation="jobCompany"], [data-testid="company-name"] a, '
            'span[data-automation="jobCompany"]'
        )
        company = (await company_el.inner_text()).strip() if company_el else "Unknown"

        # Location
        loc_el = await card.query_selector(
            'a[data-automation="jobLocation"], [data-testid="job-card-location"], '
            'span[data-automation="jobLocation"]'
        )
        job_location = (await loc_el.inner_text()).strip() if loc_el else (location or "Hong Kong")

        # Salary
        salary_el = await card.query_selector(
            '[data-automation="jobSalary"], [data-testid="job-card-salary"], '
            'span.salary'
        )
        salary_text = (await salary_el.inner_text()).strip() if salary_el else ""
        salary = _parse_jobsdb_salary(salary_text) if salary_text else None

        # Description / snippet
        desc_el = await card.query_selector(
            '[data-automation="jobShortDescription"], [data-testid="job-card-description"], '
            'span.job-description'
        )
        description = (await desc_el.inner_text()).strip() if desc_el else ""

        # Tags
        tag_els = await card.query_selector_all(
            '[data-automation="jobTag"], .badge, .tag'
        )
        tags = [await t.inner_text() for t in tag_els]

        # Build URL
        if href.startswith("http"):
            url = href
        elif href.startswith("/"):
            url = f"https://hk.jobsdb.com{href}"
        else:
            url = f"https://hk.jobsdb.com/{href}"

        return Job(
            source=JobSource.JOBSDB,
            title=title,
            company=company,
            location=job_location,
            url=url,
            description=description,
            salary=salary,
            tags=tags,
        )

    async def _scrape_via_api(
        self, page: Page, query: str, location: str | None, limit: int,
    ) -> list[Job]:
        """Fallback: use JobsDB's internal GraphQL/REST API."""
        jobs: list[Job] = []

        # JobsDB uses a GraphQL API under the hood
        api_url = "https://xapi.supercharge-srp.co/job-search/graphql?country=hk&is498"

        import json

        payload = {
            "query": (
                "query getJobs($keywords: String, $pageSize: Int) {"
                "  jobs(keywords: $keywords, pageSize: $pageSize) {"
                "    jobs { id title companyName location { label } salary { label }"
                "      abstract listingUrl }"
                "  }"
                "}"
            ),
            "variables": {"keywords": query, "pageSize": min(limit, 30)},
        }

        try:
            response = await page.evaluate(
                """async (payload) => {
                    const resp = await fetch(payload.url, {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify(payload.body),
                    });
                    return await resp.json();
                }""",
                {"url": api_url, "body": payload},
            )

            if response and "data" in response:
                for item in response["data"].get("jobs", {}).get("jobs", [])[:limit]:
                    url = item.get("listingUrl", "")
                    if not url.startswith("http"):
                        url = f"https://hk.jobsdb.com{url}"

                    jobs.append(Job(
                        source=JobSource.JOBSDB,
                        title=item.get("title", "Unknown"),
                        company=item.get("companyName", "Unknown"),
                        location=item.get("location", {}).get("label", location or "Hong Kong"),
                        url=url,
                        description=item.get("abstract", ""),
                        salary=_parse_jobsdb_salary(item.get("salary", {}).get("label", "")),
                        tags=[],
                    ))
        except Exception as e:
            logger.warning("JobsDB API scrape failed: %s", e)

        return jobs

    @staticmethod
    async def _human_scroll(page: Page, scroll_count: int = 3) -> None:
        """Scroll page like a human to trigger lazy loading."""
        import asyncio

        for _ in range(scroll_count):
            scroll_amount = random.randint(300, 700)
            await page.evaluate(f"window.scrollBy(0, {scroll_amount})")
            await asyncio.sleep(random.uniform(0.8, 2.0))

    @staticmethod
    async def _human_delay(lo: float = 0.5, hi: float = 1.5) -> None:
        """Sleep for a random duration to mimic human browsing."""
        import asyncio
        await asyncio.sleep(random.uniform(lo, hi))

    @staticmethod
    async def _fetch_job_detail(context: BrowserContext, url: str) -> str | None:
        """Open a job detail page and extract the full description from jobAdDetails.

        Args:
            context: Playwright BrowserContext (reuses cookies/stealth).
            url: The job detail page URL.

        Returns:
            Full job description text, or None if extraction failed.
        """
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

            # Wait for the job details section
            detail_el = None
            selectors = [
                '[data-automation="jobAdDetails"]',
                '[data-automation="jobDescription"]',
                '.job-description',
                'div[class*="jobAdDetails"]',
            ]

            for sel in selectors:
                try:
                    await page.wait_for_selector(sel, timeout=8_000)
                    detail_el = await page.query_selector(sel)
                    if detail_el:
                        break
                except Exception:
                    continue

            if not detail_el:
                logger.debug("jobAdDetails not found for %s", url)
                return None

            # Get the full text content
            text = await detail_el.inner_text()
            return text.strip() if text else None

        except Exception as e:
            logger.warning("Failed to fetch job detail from %s: %s", url, e)
            return None
        finally:
            await page.close()


def _parse_jobsdb_salary(text: str) -> SalaryRange | None:
    """Parse JobsDB salary text into SalaryRange.

    Examples:
        "HK$25,000 - HK$35,000 /month"
        "$30K - $50K"
        "HK$300,000 - HK$500,000 /year"
    """
    import re

    if not text:
        return None

    text = text.replace(",", "").replace("HK$", "").replace("$", "").strip()

    # Monthly pattern: "25000 - 35000 /month"
    monthly = re.search(r"(\d+)[Kk]?\s*[-–]\s*(\d+)[Kk]?\s*/?\s*month", text, re.IGNORECASE)
    if monthly:
        low = int(monthly.group(1))
        high = int(monthly.group(2))
        # Handle K suffix
        if low < 1000:
            low *= 1000
        if high < 1000:
            high *= 1000
        return SalaryRange(min_annual=low * 12, max_annual=high * 12, currency="HKD")

    # Annual pattern: "300000 - 500000 /year"
    annual = re.search(r"(\d+)[Kk]?\s*[-–]\s*(\d+)[Kk]?\s*/?\s*(?:year|annum)", text, re.IGNORECASE)
    if annual:
        low = int(annual.group(1))
        high = int(annual.group(2))
        if low < 1000:
            low *= 1000
        if high < 1000:
            high *= 1000
        return SalaryRange(min_annual=low, max_annual=high, currency="HKD")

    # Generic range: "25000 - 35000"
    generic = re.search(r"(\d+)[Kk]?\s*[-–]\s*(\d+)[Kk]?", text)
    if generic:
        low = int(generic.group(1))
        high = int(generic.group(2))
        if low < 1000:
            low *= 1000
        if high < 1000:
            high *= 1000
        # Assume monthly if values are reasonable
        if low < 200_000:
            return SalaryRange(min_annual=low * 12, max_annual=high * 12, currency="HKD")
        return SalaryRange(min_annual=low, max_annual=high, currency="HKD")

    return None
