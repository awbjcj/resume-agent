import time
import urllib.parse

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from resume_agent.config import get_settings
from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.scraper.models import ScrapedCard
from resume_agent.discovery.scraper.parser import parse_job_detail, parse_search_cards
from resume_agent.discovery.search_config import SearchConfig

_SEARCH_URL = "https://www.linkedin.com/jobs/search/"

# Containers that signal the meaningful content has rendered. Waiting on these
# replaces a blind sleep: navigation returns as soon as the cards / JD exist.
_CARDS_SELECTOR = "div.base-card"
_DETAIL_SELECTOR = "div.show-more-less-html__markup, .description__text"


def _search_url(config: SearchConfig) -> str:
    params: dict[str, str] = {}
    terms = list(dict.fromkeys([*config.titles, *config.keywords]))
    if terms:
        params["keywords"] = " ".join(terms)
    if config.locations:
        params["location"] = config.locations[0]
    if not params:
        return _SEARCH_URL
    return _SEARCH_URL + "?" + urllib.parse.urlencode(params)


class LinkedInScraper:
    """Connector over a persistent, logged-in burner LinkedIn profile.

    First run: a browser window opens; log in by hand once. The session persists
    in ``user_data_dir`` for subsequent runs. Pacing is deliberate and capped.
    """

    name = "linkedin"

    def __init__(
        self,
        user_data_dir: str = ".linkedin_profile",
        headless: bool = False,
        pace_seconds: float = 1.0,
        render_timeout_ms: int = 8000,
    ):
        self.user_data_dir = user_data_dir
        self.headless = headless
        # Politeness gap between requests (anti-bot throttle), separate from the
        # render wait below so each can be tuned without affecting the other.
        self.pace_seconds = pace_seconds
        self.render_timeout_ms = render_timeout_ms
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    def _ensure_page(self) -> Page:
        """Lazily launch the persistent context once and reuse its page.

        Launching is deferred to the first navigation so subclasses that stub
        ``_search_html``/``_detail_html`` (e.g. tests) never spin up a browser.
        """
        if self._page is None:
            self._playwright = sync_playwright().start()
            self._context = self._playwright.chromium.launch_persistent_context(
                self.user_data_dir, headless=self.headless
            )
            self._page = self._context.new_page()
        return self._page

    def _close_browser(self) -> None:
        if self._context is not None:
            self._context.close()
            self._context = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None
        self._page = None

    def _content_for_url(
        self, url: str, *, wait_selector: str | None = None, scroll: bool = False
    ) -> str:
        page = self._ensure_page()
        page.goto(url, wait_until="domcontentloaded")
        self._wait_for(page, wait_selector)
        if scroll:
            page.mouse.wheel(0, 4000)
            # Let lazily loaded cards settle; bounded so a quiet network
            # (or none) never hangs the scrape.
            try:
                page.wait_for_load_state("networkidle", timeout=self.render_timeout_ms)
            except PlaywrightTimeoutError:
                pass
        time.sleep(self.pace_seconds)
        return page.content()

    def _wait_for(self, page: Page, selector: str | None) -> None:
        """Block until ``selector`` renders, or give up after the render timeout.

        A timeout is swallowed on purpose: the parsers treat a missing container
        as an empty result (skipped job) rather than an error.
        """
        if selector is None:
            return
        try:
            page.wait_for_selector(selector, timeout=self.render_timeout_ms)
        except PlaywrightTimeoutError:
            pass

    def fetch(self, search: SearchConfig, limit: int | None = None) -> list[RawJob]:
        try:
            cards = parse_search_cards(self._search_html(search))
            if limit is not None:
                cards = cards[:limit]
            jobs: list[RawJob] = []
            for card in cards:
                jd_text = parse_job_detail(self._detail_html(card)).strip()
                if not jd_text:
                    continue
                jobs.append(
                    RawJob(
                        source=self.name,
                        url=card.url,
                        company=card.company,
                        title=card.title,
                        location=card.location,
                        jd_text=jd_text,
                        posted_at=card.posted_at,
                    )
                )
            return jobs
        finally:
            self._close_browser()

    def _search_html(self, search: SearchConfig) -> str:
        return self._content_for_url(
            _search_url(search), wait_selector=_CARDS_SELECTOR, scroll=True
        )

    def _detail_html(self, card: ScrapedCard) -> str:
        if not card.url:
            return ""
        return self._content_for_url(card.url, wait_selector=_DETAIL_SELECTOR)


def build_linkedin_scraper() -> LinkedInScraper:
    settings = get_settings()
    return LinkedInScraper(user_data_dir=settings.linkedin_user_data_dir)
