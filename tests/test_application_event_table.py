from datetime import datetime, timezone

from sqlmodel import Session, select

from resume_agent.db import init_db, make_engine
from resume_agent.tracking.tables import Application, ApplicationEvent, Job


def _engine():
    engine = make_engine("sqlite://")
    init_db(engine)
    return engine


def test_create_all_makes_the_table_without_a_migration():
    engine = _engine()
    with Session(engine) as session:
        job = Job(source="test", company="Acme", title="SWE")
        session.add(job)
        session.commit()
        session.refresh(job)
        app = Application(job_id=job.id, status="submitted")
        session.add(app)
        session.commit()
        session.refresh(app)
        event = ApplicationEvent(
            application_id=app.id,
            kind="technical_round",
            sequence=1,
            occurred_at=datetime(2026, 3, 3, 19, 0, tzinfo=timezone.utc),
            timezone="America/New_York",
            duration_minutes=60,
            modality="virtual",
            platform="zoom",
        )
        session.add(event)
        session.commit()
        stored = session.exec(select(ApplicationEvent)).one()
        assert stored.kind == "technical_round"
        assert stored.result == "pending"
        assert stored.all_day is False
        assert stored.source == "manual"
        assert stored.schema_version == 1


def test_comp_fields_default_to_none():
    engine = _engine()
    with Session(engine) as session:
        job = Job(source="test")
        session.add(job)
        session.commit()
        session.refresh(job)
        app = Application(job_id=job.id)
        session.add(app)
        session.commit()
        session.refresh(app)
        event = ApplicationEvent(application_id=app.id, kind="recruiter_screen")
        session.add(event)
        session.commit()
        stored = session.exec(select(ApplicationEvent)).one()
        assert stored.comp_base is None
        assert stored.comp_currency is None
        assert stored.reflection is None
