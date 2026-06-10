from sqlmodel import Session, SQLModel, create_engine

from resume_agent.discovery.scraper.ingest import ingest_scraped
from resume_agent.discovery.scraper.models import ScrapedCard
from resume_agent.discovery.search_config import SearchConfig
from resume_agent.tracking.repository import jobs_by_status
from resume_agent.tracking.tables import JobStatus


class _FakeSource:
    """A JobSource that returns cards and canned JD text."""

    def __init__(self, empty_second: bool = False):
        self.empty_second = empty_second
        self.fetched: list[str | None] = []

    def search(self, config):
        return [
            ScrapedCard("1", "Backend Engineer", "Acme", "Remote", "https://li/jobs/view/1/"),
            ScrapedCard("2", "Platform Engineer", "Beta", "London", "https://li/jobs/view/2/"),
        ]

    def fetch_jd(self, card):
        self.fetched.append(card.job_id)
        if self.empty_second and card.job_id == "2":
            return " "
        return f"JD for {card.title}"


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_ingest_scraped_inserts_raw_jobs():
    source = _FakeSource()
    with _session() as s:
        added = ingest_scraped(s, source, SearchConfig())
        assert added == 2
        assert source.fetched == ["1", "2"]
        raw = jobs_by_status(s, JobStatus.raw.value)
        assert {j.title for j in raw} == {"Backend Engineer", "Platform Engineer"}
        assert all(j.source == "linkedin" for j in raw)


def test_ingest_scraped_dedupes_on_second_run():
    source = _FakeSource()
    with _session() as s:
        assert ingest_scraped(s, source, SearchConfig()) == 2
        assert ingest_scraped(s, source, SearchConfig()) == 0


def test_ingest_scraped_respects_limit():
    source = _FakeSource()
    with _session() as s:
        added = ingest_scraped(s, source, SearchConfig(), limit=1)
        assert added == 1
        assert source.fetched == ["1"]


def test_ingest_scraped_skips_empty_jd_text():
    source = _FakeSource(empty_second=True)
    with _session() as s:
        added = ingest_scraped(s, source, SearchConfig())
        assert added == 1
        assert {j.title for j in jobs_by_status(s, JobStatus.raw.value)} == {"Backend Engineer"}
