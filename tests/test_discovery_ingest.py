from sqlmodel import Session, SQLModel, create_engine

from resume_agent.discovery.ingest import add_job
from resume_agent.tracking.tables import JobStatus


def _session() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_add_job_inserts_raw_and_strips_fields():
    with _session() as s:
        job = add_job(s, source="manual", jd_text="  hello  ", company="  Acme ", title=" Eng ")
        assert job is not None
        assert job.status == JobStatus.raw.value
        assert job.jd_text == "hello"
        assert job.company == "Acme"
        assert job.title == "Eng"


def test_add_job_dedupes_identical_jd():
    with _session() as s:
        first = add_job(s, source="manual", jd_text="same text")
        dup = add_job(s, source="manual", jd_text="same text")
        assert first is not None
        assert dup is None


def test_add_job_dedupes_by_url():
    with _session() as s:
        add_job(s, source="manual", jd_text="a", url="http://x/1")
        dup = add_job(s, source="manual", jd_text="b", url="http://x/1")
        assert dup is None
