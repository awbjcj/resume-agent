from datetime import datetime, timezone
from pathlib import Path

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.scraper.linkedin import _FEED_URL, LinkedInScraper
from resume_agent.discovery.search_config import SearchConfig

FIXTURES = Path(__file__).parent / "fixtures" / "linkedin"


class _FakeBrowserScraper(LinkedInScraper):
    def _search_html(self, search):
        return (FIXTURES / "search.html").read_text(encoding="utf-8")

    def _detail_html(self, card):
        return (FIXTURES / "job.html").read_text(encoding="utf-8")


def test_linkedin_fetch_returns_rawjobs_attributed_to_linkedin():
    jobs = _FakeBrowserScraper().fetch(SearchConfig())
    assert len(jobs) == 2
    assert all(isinstance(j, RawJob) for j in jobs)
    assert all(j.source == "linkedin" for j in jobs)
    assert jobs[0].title == "Senior Backend Engineer"
    assert "5+ years of Python." in jobs[0].jd_text


def test_linkedin_fetch_respects_limit():
    assert len(_FakeBrowserScraper().fetch(SearchConfig(), limit=1)) == 1


def test_linkedin_fetch_threads_search_card_posted_at():
    class _FakeDatedScraper(LinkedInScraper):
        def _search_html(self, search):
            return """
            <html><body>
              <div class="base-card" data-entity-urn="urn:li:jobPosting:3700000001">
                <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/3700000001/?trk=public_jobs_jserp-result_search-card"></a>
                <h3 class="base-search-card__title">Senior Backend Engineer</h3>
                <h4 class="base-search-card__subtitle">Acme Corp</h4>
                <span class="job-search-card__location">Remote, United States</span>
                <time class="job-search-card__listdate" datetime="2026-06-01">2 weeks ago</time>
              </div>
            </body></html>
            """

        def _detail_html(self, card):
            return """
            <html><body>
              <div class="show-more-less-html__markup">Build pipelines.</div>
            </body></html>
            """

    assert _FakeDatedScraper().fetch(SearchConfig())[0].posted_at == datetime(
        2026, 6, 1, tzinfo=timezone.utc
    )


class _ScriptedPage:
    """Minimal Playwright Page stand-in for exercising the login flow.

    ``goto_resolves`` simulates LinkedIn's redirects (e.g. an unauthenticated
    /feed bounces to /authwall); a submit click resolves to ``click_url``.
    """

    def __init__(self, goto_resolves, click_url=None):
        self.goto_resolves = goto_resolves
        self.click_url = click_url
        self.url = ""
        self.filled: dict[str, str] = {}
        self.clicked: list[str] = []

    def goto(self, url, wait_until=None):
        self.url = self.goto_resolves.get(url, url)

    def fill(self, selector, value):
        self.filled[selector] = value

    def click(self, selector):
        self.clicked.append(selector)
        if self.click_url is not None:
            self.url = self.click_url

    def wait_for_url(self, predicate, timeout=None):
        return None


def test_ensure_logged_in_skips_login_when_session_already_valid():
    page = _ScriptedPage(goto_resolves={_FEED_URL: _FEED_URL})
    scraper = LinkedInScraper(email="a@b.com", password="pw")
    scraper._ensure_logged_in(page)
    assert page.filled == {}  # already authenticated: no credential entry
    assert scraper._logged_in is True


def test_close_browser_clears_logged_in_flag():
    # A torn-down context's session must not be trusted by a later fetch.
    scraper = LinkedInScraper()
    scraper._logged_in = True
    scraper._close_browser()
    assert scraper._logged_in is False


def test_ensure_logged_in_fills_credentials_when_unauthenticated():
    page = _ScriptedPage(
        goto_resolves={_FEED_URL: "https://www.linkedin.com/authwall"},
        click_url=_FEED_URL,
    )
    scraper = LinkedInScraper(email="burner@example.com", password="s3cret")
    scraper._ensure_logged_in(page)
    assert page.filled["#username"] == "burner@example.com"
    assert page.filled["#password"] == "s3cret"
    assert "button[type='submit']" in page.clicked
    assert scraper._logged_in is True
