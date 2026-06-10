import time
import urllib.parse

from playwright.sync_api import sync_playwright

from resume_agent.config import get_settings
from resume_agent.discovery.scraper.models import ScrapedCard
from resume_agent.discovery.scraper.parser import parse_job_detail, parse_search_cards
from resume_agent.discovery.search_config import SearchConfig

_SEARCH_URL = "https://www.linkedin.com/jobs/search/"


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
    """Playwright driver over a persistent, logged-in burner profile.

    First run: a browser window opens; log in by hand once. The session persists
    in ``user_data_dir`` for subsequent runs. Pacing is deliberate and capped.
    """

    def __init__(
        self,
        user_data_dir: str = ".linkedin_profile",
        headless: bool = False,
        pace_seconds: float = 2.0,
    ):
        self.user_data_dir = user_data_dir
        self.headless = headless
        self.pace_seconds = pace_seconds

    def _content_for_url(self, url: str, *, scroll: bool = False) -> str:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                self.user_data_dir, headless=self.headless
            )
            try:
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded")
                time.sleep(self.pace_seconds)
                if scroll:
                    page.mouse.wheel(0, 4000)
                    time.sleep(self.pace_seconds)
                return page.content()
            finally:
                context.close()

    def search(self, config: SearchConfig) -> list[ScrapedCard]:
        html = self._content_for_url(_search_url(config), scroll=True)
        return parse_search_cards(html)

    def fetch_jd(self, card: ScrapedCard) -> str:
        if not card.url:
            return ""
        html = self._content_for_url(card.url)
        return parse_job_detail(html)


def build_linkedin_scraper() -> LinkedInScraper:
    settings = get_settings()
    return LinkedInScraper(user_data_dir=settings.linkedin_user_data_dir)
