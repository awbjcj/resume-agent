from sqlmodel import Session, SQLModel, create_engine

from resume_agent.discovery.ingest import add_job
from resume_agent.tracking.repository import get_cover_letter, save_cover_letter
from resume_agent.tracking.tables import CoverLetter


def _session():
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_save_and_get_cover_letter():
    with _session() as s:
        job = add_job(s, source="manual", jd_text="jd", company="Acme", title="Eng")
        assert job is not None and job.id is not None
        saved = save_cover_letter(
            s,
            CoverLetter(
                job_id=job.id, content_json={"greeting": "Hi"}, fact_check_passed=True
            ),
        )
        assert saved.id is not None
        fetched = get_cover_letter(s, saved.id)
        assert fetched is not None
        assert fetched.job_id == job.id
        assert fetched.fact_check_passed is True
