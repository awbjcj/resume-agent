from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.known_jobs import build_known_index
from resume_agent.tracking.repository import _prune_rows
from resume_agent.tracking.tables import Job, JobStatus


def _engine_with_job():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            Job(
                source="greenhouse",
                url="https://example.test/jobs/42",
                company="Acme",
                title="Engineer",
                location="Boston, MA",
                dedup_key="acme|engineer",
                jd_text="large description",
                fit_score=73,
                status=JobStatus.rejected.value,
            )
        )
        session.commit()
    return engine


def _count_job_loads(action) -> int:
    loaded = 0

    def record_load(_job, _context):
        nonlocal loaded
        loaded += 1

    event.listen(Job, "load", record_load)
    try:
        action()
    finally:
        event.remove(Job, "load", record_load)
    return loaded


def test_known_job_index_projects_only_matching_fields():
    engine = _engine_with_job()

    def build_and_match():
        with Session(engine) as session:
            index = build_known_index(session)
            assert index.match(
                RawJob(
                    source="lever",
                    url="https://example.test/jobs/42",
                    company="Acme",
                    title="Engineer",
                    location="Boston, MA",
                    jd_text="new",
                )
            ) is not None

    assert _count_job_loads(build_and_match) == 0


def test_prune_scan_projects_only_prune_fields():
    engine = _engine_with_job()

    def scan():
        with Session(engine) as session:
            rows = _prune_rows(session)
            assert len(rows) == 1
            assert rows[0].status == JobStatus.rejected.value
            assert rows[0].fit_score == 73

    assert _count_job_loads(scan) == 0
