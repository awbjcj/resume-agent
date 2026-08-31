from datetime import datetime, timedelta, timezone
import inspect

from sqlmodel import Session, select

from resume_tailor_harness.db import init_db, make_engine
from resume_tailor_harness.services.reminder_scheduler import (
    REMINDER_INTERVAL_SECONDS,
    run_reminder_pass,
)
from resume_tailor_harness.tracking.tables import (
    Application,
    ApplicationEvent,
    Job,
    Notification,
)

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)


def _require_id(value: int | None) -> int:
    assert value is not None
    return value


def _session() -> Session:
    engine = make_engine("sqlite://")
    init_db(engine)
    return Session(engine)


def test_reminder_pass_requires_no_gmail_token_and_is_idempotent() -> None:
    session = _session()
    job = Job(source="test", company="Acme", title="SWE")
    session.add(job)
    session.commit()
    session.refresh(job)
    application = Application(job_id=_require_id(job.id), status="interview")
    session.add(application)
    session.commit()
    session.refresh(application)
    session.add(
        ApplicationEvent(
            application_id=_require_id(application.id),
            kind="technical_round",
            occurred_at=NOW + timedelta(hours=20),
        )
    )
    session.commit()
    assert run_reminder_pass(session, now=NOW) == {"followUp": 0, "events": 1}
    assert run_reminder_pass(session, now=NOW) == {"followUp": 0, "events": 0}
    assert len(session.exec(select(Notification)).all()) == 1


def test_reminder_pass_still_owns_stale_follow_ups() -> None:
    session = _session()
    job = Job(source="test", company="Acme", title="SWE")
    session.add(job)
    session.commit()
    session.refresh(job)
    session.add(
        Application(
            job_id=_require_id(job.id),
            status="submitted",
            updated_at=NOW - timedelta(days=30),
        )
    )
    session.commit()
    assert run_reminder_pass(session, now=NOW)["followUp"] == 1


def test_scheduler_is_hourly_and_gmail_sync_no_longer_mentions_reminders() -> None:
    from resume_tailor_harness.services import gmail_sync

    assert REMINDER_INTERVAL_SECONDS == 3600
    assert "create_follow_up_reminders" not in inspect.getsource(gmail_sync)
