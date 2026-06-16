from datetime import datetime, timezone
from pathlib import Path

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.scraper.linkedin import LinkedInScraper
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
