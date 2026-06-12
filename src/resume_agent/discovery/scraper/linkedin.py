import time
import urllib.parse

from playwright.sync_api import sync_playwright

from resume_agent.config import get_settings
from resume_agent.discovery.connectors.base import RawJob
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
    """Connector over a persistent, logged-in burner LinkedIn profile.

    First run: a browser window opens; log in by hand once. The session persists
    in ``user_data_dir`` for subsequent runs. Pacing is deliberate and capped.
    """

    name = "linkedin"

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

    def fetch(self, search: SearchConfig, limit: int | None = None) -> list[RawJob]:
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
                )
            )
        return jobs

    def _search_html(self, search: SearchConfig) -> str:
        return self._content_for_url(_search_url(search), scroll=True)

    def _detail_html(self, card: ScrapedCard) -> str:
        if not card.url:
            return ""
        return self._content_for_url(card.url)


def build_linkedin_scraper() -> LinkedInScraper:
    settings = get_settings()
    return LinkedInScraper(user_data_dir=settings.linkedin_user_data_dir)
