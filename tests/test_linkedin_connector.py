from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import Error as PlaywrightError

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.scraper.linkedin import (
    _FEED_URL,
    LinkedInScraper,
    _playwright_failure_reason,
    _search_url,
)
from resume_agent.discovery.search_config import SearchConfig

FIXTURES = Path(__file__).parent / "fixtures" / "linkedin"


class _FakeBrowserScraper(LinkedInScraper):
    def _search_html(self, search):
        return (FIXTURES / "search.html").read_text(encoding="utf-8")

    def _detail_html(self, card):
        return (FIXTURES / "job.html").read_text(encoding="utf-8")


def test_linkedin_fetch_returns_rawjobs_attributed_to_linkedin():
    jobs = _FakeBrowserScraper().fetch(SearchConfig()).jobs
    assert len(jobs) == 2
    assert all(isinstance(j, RawJob) for j in jobs)
    assert all(j.source == "linkedin" for j in jobs)
    assert jobs[0].title == "Senior Backend Engineer"
    assert "5+ years of Python." in jobs[0].jd_text


def test_linkedin_fetch_respects_limit():
    assert len(_FakeBrowserScraper().fetch(SearchConfig(), limit=1).jobs) == 1


def test_linkedin_configured_limit_overrides_global():
    scraper = _FakeBrowserScraper(configured_limit=1)
    assert len(scraper.fetch(SearchConfig(), limit=5).jobs) == 1


def test_linkedin_fetch_isolates_failed_detail_navigation():
    class _PartiallyDeadScraper(LinkedInScraper):
        def _search_html(self, search):
            return """
            <html><body>
              <div class="base-card" data-entity-urn="urn:li:jobPosting:3700000001">
                <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/3700000001/"></a>
                <h3 class="base-search-card__title">Dead Engineer</h3>
                <h4 class="base-search-card__subtitle">Acme Corp</h4>
                <span class="job-search-card__location">Remote, United States</span>
              </div>
              <div class="base-card" data-entity-urn="urn:li:jobPosting:3700000002">
                <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/3700000002/"></a>
                <h3 class="base-search-card__title">Live Engineer</h3>
                <h4 class="base-search-card__subtitle">Acme Corp</h4>
                <span class="job-search-card__location">Remote, United States</span>
              </div>
            </body></html>
            """

        def _detail_html(self, card):
            if card.title == "Dead Engineer":
                raise PlaywrightError("Page.goto: net::ERR_HTTP_RESPONSE_CODE_FAILURE")
            return """
            <html><body>
              <div class="show-more-less-html__markup">Build useful systems.</div>
            </body></html>
            """

    result = _PartiallyDeadScraper().fetch(SearchConfig())

    assert [job.title for job in result.jobs] == ["Live Engineer"]
    assert result.failures == {
        "https://www.linkedin.com/jobs/view/3700000001/": (
            "Page.goto: net::ERR_HTTP_RESPONSE_CODE_FAILURE"
        )
    }


def test_linkedin_fetch_skips_known_cards_before_detail_scrape():
    # skip_seen must short-circuit before _detail_html — the visible-browser
    # detail render is the whole cost the known-job skip exists to avoid.
    scraped: list[str] = []

    class _RecordingScraper(LinkedInScraper):
        def _search_html(self, search):
            return """
            <html><body>
              <div class="base-card" data-entity-urn="urn:li:jobPosting:3700000001">
                <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/3700000001/"></a>
                <h3 class="base-search-card__title">Known Engineer</h3>
                <h4 class="base-search-card__subtitle">Acme Corp</h4>
                <span class="job-search-card__location">Remote, United States</span>
              </div>
              <div class="base-card" data-entity-urn="urn:li:jobPosting:3700000002">
                <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/3700000002/"></a>
                <h3 class="base-search-card__title">New Engineer</h3>
                <h4 class="base-search-card__subtitle">Acme Corp</h4>
                <span class="job-search-card__location">Remote, United States</span>
              </div>
            </body></html>
            """

        def _detail_html(self, card):
            assert card.url is not None
            scraped.append(card.url)
            return """
            <html><body>
              <div class="show-more-less-html__markup">Build useful systems.</div>
            </body></html>
            """

    result = _RecordingScraper().fetch(
        SearchConfig(),
        skip_seen=lambda row: (
            row.url == "https://www.linkedin.com/jobs/view/3700000001/"
        ),
    )

    assert scraped == ["https://www.linkedin.com/jobs/view/3700000002/"]
    assert [job.title for job in result.jobs] == ["New Engineer"]


def test_playwright_failure_reason_handles_empty_message():
    # An exception with no message must not IndexError on splitlines()[0].
    assert _playwright_failure_reason(PlaywrightError("")) == "Error"


def test_playwright_failure_reason_strips_url_tail():
    reason = _playwright_failure_reason(
        PlaywrightError("Page.goto: net::ERR_ABORTED at https://example.com/x")
    )
    assert reason == "Page.goto: net::ERR_ABORTED"


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

    assert _FakeDatedScraper().fetch(SearchConfig()).jobs[0].posted_at == datetime(
        2026, 6, 1, tzinfo=timezone.utc
    )


def test_search_url_uses_one_source_query_not_every_title_and_keyword():
    url = _search_url(
        SearchConfig(
            titles=["Software Engineer", "AI Engineer"],
            keywords=["python", "rag"],
            locations=["Ann Arbor, MI"],
        ),
        geo_resolver=lambda loc: None,
    )
    params = parse_qs(urlsplit(url).query)

    assert params["keywords"] == ["Software Engineer"]
    assert params["location"] == ["Ann Arbor, MI"]


def test_search_url_emits_native_filters():
    cfg = SearchConfig(
        titles=["AI Engineer"],
        locations=["Detroit, MI"],
        remote_policy=["remote"],
        experience_levels=["mid-senior", "director"],
        employment_types=["full_time"],
        min_salary=130000,
        distance=40,
        max_days_old=30,
    )
    url = _search_url(cfg, geo_resolver=lambda loc: "103624908")
    params = parse_qs(urlsplit(url).query)

    assert params["keywords"] == ["AI Engineer"]
    assert params["geoId"] == ["103624908"]
    assert params["distance"] == ["40"]
    assert params["f_WT"] == ["2"]
    assert params["f_E"] == ["4,5"]
    assert params["f_JT"] == ["F"]
    assert params["f_TPR"] == ["r2592000"]
    assert params["f_SB2"] == ["5"]
    assert params["sortBy"] == ["DD"]


def test_search_url_skips_remote_as_a_geography():
    resolved: list[str] = []

    def _resolve(location: str) -> str:
        resolved.append(location)
        return "103624908"

    cfg = SearchConfig(
        titles=["AI Engineer"],
        locations=["Remote", "Detroit, MI"],
        remote_policy=["remote"],
    )
    params = parse_qs(urlsplit(_search_url(cfg, geo_resolver=_resolve)).query)

    assert resolved == ["Detroit, MI"]
    assert params["geoId"] == ["103624908"]
    assert params["f_WT"] == ["2"]


def test_search_url_omits_location_when_only_non_geographic_labels_exist():
    cfg = SearchConfig(
        titles=["AI Engineer"],
        locations=["Remote", "Worldwide", "Anywhere"],
        remote_policy=["remote"],
    )
    params = parse_qs(
        urlsplit(
            _search_url(
                cfg,
                geo_resolver=lambda location: (_ for _ in ()).throw(
                    AssertionError(f"must not resolve non-geography {location}")
                ),
            )
        ).query
    )

    assert "geoId" not in params
    assert "location" not in params
    assert params["f_WT"] == ["2"]


def test_search_url_joins_multiple_remote_policies():
    cfg = SearchConfig(
        titles=["AI Engineer"], remote_policy=["remote", "hybrid", "remote"]
    )
    url = _search_url(cfg, geo_resolver=lambda loc: None)
    params = parse_qs(urlsplit(url).query)
    assert params["f_WT"] == ["2,3"]


def test_search_url_falls_back_to_text_location_when_geo_unresolved():
    cfg = SearchConfig(titles=["AI Engineer"], locations=["Greater Detroit Area"])
    url = _search_url(cfg, geo_resolver=lambda loc: None)
    params = parse_qs(urlsplit(url).query)
    assert "geoId" not in params
    assert params["location"] == ["Greater Detroit Area"]


def test_search_url_omits_unset_filters():
    cfg = SearchConfig(titles=["AI Engineer"])
    params = parse_qs(urlsplit(_search_url(cfg, geo_resolver=lambda loc: None)).query)
    for key in ("f_WT", "f_E", "f_JT", "f_TPR", "f_SB2", "distance", "sortBy"):
        assert key not in params


def test_linkedin_fetch_uses_next_source_query_until_limit():
    class _MultiSearchScraper(LinkedInScraper):
        def __init__(self):
            super().__init__()
            self.queries: list[str] = []

        def _search_html(self, search):
            term = (search.titles or search.keywords)[0]
            self.queries.append(term)
            job_id = {"Software Engineer": "3700000001", "AI Engineer": "3700000002"}[
                term
            ]
            return f"""
            <html><body>
              <div class="base-card" data-entity-urn="urn:li:jobPosting:{job_id}">
                <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/{job_id}/"></a>
                <h3 class="base-search-card__title">{term}</h3>
                <h4 class="base-search-card__subtitle">Acme Corp</h4>
                <span class="job-search-card__location">Remote, United States</span>
              </div>
            </body></html>
            """

        def _detail_html(self, card):
            return """
            <html><body>
              <div class="show-more-less-html__markup">Build useful systems.</div>
            </body></html>
            """

    scraper = _MultiSearchScraper()
    jobs = scraper.fetch(
        SearchConfig(titles=["Software Engineer", "AI Engineer"], keywords=["python"]),
        limit=2,
    ).jobs

    assert scraper.queries == ["Software Engineer", "AI Engineer"]
    assert [job.title for job in jobs] == ["Software Engineer", "AI Engineer"]


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
