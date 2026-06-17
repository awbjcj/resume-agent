import re
import time
import urllib.parse
from typing import Callable, Literal, Protocol

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from resume_agent.config import get_settings
from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.scraper.models import ScrapedCard
from resume_agent.discovery.scraper.parser import parse_job_detail, parse_search_cards
from resume_agent.discovery.search_config import SearchConfig

_SEARCH_URL = "https://www.linkedin.com/jobs/search/"
_LOGIN_URL = "https://www.linkedin.com/login"
_FEED_URL = "https://www.linkedin.com/feed/"

# Containers that signal the meaningful content has rendered. Waiting on these
# replaces a blind sleep: navigation returns as soon as the cards / JD exist.
_CARDS_SELECTOR = "div.base-card"
_DETAIL_SELECTOR = "div.show-more-less-html__markup, .description__text"

# How long to wait for a human to finish a manual login / 2FA / captcha before
# giving up, when credentials are absent or LinkedIn throws a checkpoint.
_MANUAL_LOGIN_TIMEOUT_MS = 180_000


class _LoginPageLike(Protocol):
    @property
    def url(self) -> str: ...

    def goto(
        self,
        url: str,
        *,
        wait_until: (
            Literal["commit", "domcontentloaded", "load", "networkidle"] | None
        ) = None,
    ) -> object: ...

    def fill(self, selector: str, value: str) -> None: ...
    def click(self, selector: str) -> None: ...

    def wait_for_url(
        self,
        predicate: str | re.Pattern[str] | Callable[[str], bool],
        *,
        timeout: int | None = None,
    ) -> None: ...


def _is_authenticated(url: str) -> bool:
    """True once we've landed on the logged-in feed (not an auth/sign-up wall)."""
    return "/feed" in url


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
        email: str = "",
        password: str = "",
    ):
        self.user_data_dir = user_data_dir
        self.headless = headless
        # Politeness gap between requests (anti-bot throttle), separate from the
        # render wait below so each can be tuned without affecting the other.
        self.pace_seconds = pace_seconds
        self.render_timeout_ms = render_timeout_ms
        # Burner credentials for automated login; empty falls back to manual.
        self.email = email
        self.password = password
        self._logged_in = False
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
        # The session lived on the context we just closed; a later fetch must
        # re-verify login on its fresh browser rather than trust this flag.
        self._logged_in = False

    def _ensure_logged_in(self, page: _LoginPageLike) -> None:
        """Establish a logged-in session before the first scrape navigation.

        Order: reuse a persisted session if the profile already holds one; else
        submit the burner credentials; else (no creds, or a checkpoint/captcha)
        wait for the human to finish by hand. A fresh, unauthenticated visit to
        LinkedIn bounces to a sign-up wall, so we drive straight to /login.
        """
        if self._logged_in:
            return
        page.goto(_FEED_URL, wait_until="domcontentloaded")
        if _is_authenticated(page.url):
            self._logged_in = True
            return
        if self.email and self.password:
            self._login_with_credentials(page)
        if not _is_authenticated(page.url):
            self._await_manual_login(page)
        self._logged_in = True

    def _login_with_credentials(self, page: _LoginPageLike) -> None:
        page.goto(_LOGIN_URL, wait_until="domcontentloaded")
        try:
            page.fill("#username", self.email)
            page.fill("#password", self.password)
            page.click("button[type='submit']")
            page.wait_for_url(
                lambda url: _is_authenticated(url) or "/checkpoint" in url,
                timeout=self.render_timeout_ms,
            )
        except PlaywrightError:
            # A timeout, a missing/changed login field, etc. — fall through so
            # the caller can offer the manual-login fallback instead of crashing.
            pass

    def _await_manual_login(self, page: _LoginPageLike) -> None:
        """Block for a human to log in (or clear a checkpoint) in the window.

        Headless mode has no window to log in through, so failing fast with a
        clear message beats silently scraping a logged-out page.
        """
        if self.headless:
            raise RuntimeError(
                "LinkedIn login required but no valid session. Set LINKEDIN_EMAIL/"
                "LINKEDIN_PASSWORD in .env, or run non-headless to log in by hand."
            )
        try:
            page.wait_for_url(
                lambda url: _is_authenticated(url), timeout=_MANUAL_LOGIN_TIMEOUT_MS
            )
        except PlaywrightTimeoutError:
            pass

    def _content_for_url(
        self, url: str, *, wait_selector: str | None = None, scroll: bool = False
    ) -> str:
        page = self._ensure_page()
        self._ensure_logged_in(page)  # type: ignore
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
    return LinkedInScraper(
        user_data_dir=settings.linkedin_user_data_dir,
        email=settings.linkedin_email,
        password=settings.linkedin_password,
    )
