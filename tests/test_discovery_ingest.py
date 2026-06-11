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


def test_add_job_dedupes_same_company_title_across_sources():
    with _session() as s:
        first = add_job(
            s,
            source="greenhouse",
            jd_text="full canonical jd",
            url="http://gh/1",
            company="Acme Corp",
            title="Senior Backend Engineer",
        )
        dup = add_job(
            s,
            source="adzuna",
            jd_text="truncated jd...",
            url="http://adz/2",
            company="acme corp",
            title="Backend Engineer",
        )
        assert first is not None
        assert dup is None


def test_add_job_keeps_distinct_when_company_or_title_missing():
    with _session() as s:
        a = add_job(s, source="manual", jd_text="text one")
        b = add_job(s, source="manual", jd_text="text two")
        assert a is not None and b is not None
