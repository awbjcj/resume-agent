from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from resume_tailor_harness.db import init_db, make_engine
from resume_tailor_harness.services.reminders import (
    DEADLINE_KIND,
    INTERVIEW_KIND,
    create_event_reminders,
)
from resume_tailor_harness.tracking.tables import Application, ApplicationEvent, Job

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)


def _require_id(value: int | None) -> int:
    assert value is not None
    return value


def _session_with_event(**event_kwargs) -> Session:
    engine = make_engine("sqlite://")
    init_db(engine)
    session = Session(engine)
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
            application_id=_require_id(application.id), **event_kwargs
        )
    )
    session.commit()
    return session


def test_interview_and_deadline_inside_their_windows_remind() -> None:
    interview = _session_with_event(
        kind="technical_round", occurred_at=NOW + timedelta(hours=20)
    )
    [created] = create_event_reminders(interview, now=NOW)
    assert created.kind == INTERVIEW_KIND
    assert "Acme" in created.evidence

    deadline = _session_with_event(
        kind="offer_deadline", occurred_at=NOW + timedelta(days=1)
    )
    assert create_event_reminders(deadline, now=NOW)[0].kind == DEADLINE_KIND


def test_past_outside_window_and_non_interview_events_do_not_remind() -> None:
    for kind, occurred_at in (
        ("technical_round", NOW - timedelta(hours=1)),
        ("technical_round", NOW + timedelta(hours=48)),
        ("application_submitted", NOW + timedelta(hours=20)),
    ):
        session = _session_with_event(kind=kind, occurred_at=occurred_at)
        assert create_event_reminders(session, now=NOW) == []


def test_cancelled_withdrawn_and_terminal_applications_do_not_remind() -> None:
    for result in ("cancelled", "withdrew"):
        session = _session_with_event(
            kind="technical_round",
            occurred_at=NOW + timedelta(hours=20),
            result=result,
        )
        assert create_event_reminders(session, now=NOW) == []
    session = _session_with_event(
        kind="technical_round", occurred_at=NOW + timedelta(hours=20)
    )
    application = session.exec(select(Application)).one()
    application.status = "rejected"
    session.add(application)
    session.commit()
    assert create_event_reminders(session, now=NOW) == []


def test_event_reminders_are_idempotent_until_rescheduled() -> None:
    session = _session_with_event(
        kind="technical_round", occurred_at=NOW + timedelta(hours=20)
    )
    assert len(create_event_reminders(session, now=NOW)) == 1
    assert create_event_reminders(session, now=NOW + timedelta(hours=1)) == []
    event = session.exec(select(ApplicationEvent)).one()
    event.occurred_at = NOW + timedelta(hours=22)
    session.add(event)
    session.commit()
    assert len(create_event_reminders(session, now=NOW)) == 1


def test_zero_lead_disables_each_event_reminder() -> None:
    interview = _session_with_event(
        kind="technical_round", occurred_at=NOW + timedelta(hours=20)
    )
    assert create_event_reminders(interview, now=NOW, interview_hours=0) == []
    deadline = _session_with_event(
        kind="offer_deadline", occurred_at=NOW + timedelta(days=1)
    )
    assert create_event_reminders(deadline, now=NOW, deadline_days=0) == []


def test_naive_sqlite_datetimes_are_interpreted_as_utc() -> None:
    session = _session_with_event(
        kind="technical_round",
        occurred_at=(NOW + timedelta(hours=20)).replace(tzinfo=None),
    )
    assert len(create_event_reminders(session, now=NOW)) == 1
