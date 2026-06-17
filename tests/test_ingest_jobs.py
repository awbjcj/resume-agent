from datetime import datetime, timezone

from sqlmodel import Session, SQLModel, create_engine

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.ingest import ingest_jobs
from resume_agent.tracking.repository import jobs_by_status
from resume_agent.tracking.tables import JobStatus


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _raw(source, n, company, title, jd):
    return RawJob(source, f"https://{source}/{n}", company, title, "Remote", jd)


def test_ingest_jobs_inserts_and_counts_per_source():
    raws = [
        _raw("greenhouse", 1, "Acme", "Backend Engineer", "JD A"),
        _raw("adzuna", 2, "Beta", "Platform Engineer", "JD B"),
    ]
    with _session() as s:
        added = ingest_jobs(s, raws)
        assert added == {"greenhouse": 1, "adzuna": 1}
        rows = jobs_by_status(s, JobStatus.raw.value)
        assert {j.source for j in rows} == {"greenhouse", "adzuna"}


def test_ingest_jobs_skips_empty_jd():
    with _session() as s:
        assert ingest_jobs(s, [_raw("adzuna", 1, "Acme", "Eng", "   ")]) == {}


def test_ingest_threads_posted_at():
    when = datetime(2026, 6, 1, tzinfo=timezone.utc)
    with _session() as s:
        ingest_jobs(
            s,
            [
                RawJob(
                    source="greenhouse",
                    url="u1",
                    company="Acme",
                    title="Eng",
                    location="Remote",
                    jd_text="hello",
                    posted_at=when,
                )
            ],
        )
        jobs = jobs_by_status(s, JobStatus.raw.value)
        assert len(jobs) == 1
        assert jobs[0].posted_at == when.replace(tzinfo=None)


def test_ingest_jobs_dedupes_same_posting_across_sources():
    raws = [
        RawJob(
            "greenhouse",
            "https://gh/1",
            "Acme Corp",
            "Senior Backend Engineer",
            "Remote",
            "Full canonical JD",
        ),
        RawJob(
            "adzuna",
            "https://adz/9",
            "acme corp",
            "Backend Engineer",
            "Remote",
            "Truncated JD...",
        ),
        RawJob(
            "linkedin",
            "https://li/7",
            "Acme Corp",
            "Sr. Backend Engineer",
            "Remote",
            "LinkedIn JD",
        ),
    ]
    with _session() as s:
        added = ingest_jobs(s, raws)
        assert added == {"greenhouse": 1}
        rows = jobs_by_status(s, JobStatus.raw.value)
        assert len(rows) == 1
        assert rows[0].source == "greenhouse"
        assert rows[0].jd_text == "Full canonical JD"
