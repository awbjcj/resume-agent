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
