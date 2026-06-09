from sqlmodel import Session, SQLModel, create_engine

from resume_agent.tracking.repository import (
    find_existing,
    jobs_by_status,
    save_job,
    status_counts,
)
from resume_agent.tracking.tables import Job, JobStatus


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_save_and_query_by_status():
    with _session() as s:
        save_job(s, Job(source="manual", jd_text="a", status=JobStatus.raw.value))
        save_job(s, Job(source="manual", jd_text="b", status=JobStatus.shortlisted.value))
        raw = jobs_by_status(s, JobStatus.raw.value)
        assert len(raw) == 1
        assert raw[0].jd_text == "a"


def test_find_existing_by_url_then_jd_text():
    with _session() as s:
        save_job(s, Job(source="manual", jd_text="hello", url="http://x/1"))
        assert find_existing(s, "http://x/1", "different") is not None  # url match
        assert find_existing(s, None, "hello") is not None             # jd_text match
        assert find_existing(s, "http://x/2", "nope") is None


def test_status_counts():
    with _session() as s:
        save_job(s, Job(source="m", jd_text="a", status=JobStatus.raw.value))
        save_job(s, Job(source="m", jd_text="b", status=JobStatus.raw.value))
        save_job(s, Job(source="m", jd_text="c", status=JobStatus.shortlisted.value))
        counts = status_counts(s)
        assert counts[JobStatus.raw.value] == 2
        assert counts[JobStatus.shortlisted.value] == 1
