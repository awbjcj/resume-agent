from datetime import datetime, timezone

from sqlmodel import Session

from resume_agent.db import init_db, make_engine
from resume_agent.tracking.repository import (
    delete_application_event,
    events_for_application,
    get_application_event,
    next_sequence,
    save_application_event,
)
from resume_agent.tracking.tables import Application, ApplicationEvent, Job


def _persisted_id(value: int | None) -> int:
    assert value is not None
    return value


def _app():
    engine = make_engine("sqlite://")
    init_db(engine)
    session = Session(engine)
    job = Job(source="test")
    session.add(job)
    session.commit()
    session.refresh(job)
    app = Application(job_id=_persisted_id(job.id))
    session.add(app)
    session.commit()
    session.refresh(app)
    return session, app


def _at(day):
    return datetime(2026, 3, day, 12, 0, tzinfo=timezone.utc)


def test_events_are_ordered_by_date_ascending():
    session, app = _app()
    for day, kind in ((9, "online_assessment"), (3, "recruiter_screen")):
        save_application_event(
            session,
            ApplicationEvent(
                application_id=_persisted_id(app.id),
                kind=kind,
                occurred_at=_at(day),
            ),
        )
    kinds = [e.kind for e in events_for_application(session, _persisted_id(app.id))]
    assert kinds == ["recruiter_screen", "online_assessment"]


def test_undated_events_sort_last():
    session, app = _app()
    save_application_event(
        session,
        ApplicationEvent(
            application_id=_persisted_id(app.id), kind="custom", custom_label="note"
        ),
    )
    save_application_event(
        session,
        ApplicationEvent(
            application_id=_persisted_id(app.id),
            kind="recruiter_screen",
            occurred_at=_at(3),
        ),
    )
    kinds = [e.kind for e in events_for_application(session, _persisted_id(app.id))]
    assert kinds == ["recruiter_screen", "custom"]


def test_next_sequence_counts_only_the_same_kind():
    session, app = _app()
    save_application_event(
        session,
        ApplicationEvent(
            application_id=_persisted_id(app.id),
            kind="technical_round",
            occurred_at=_at(3),
        ),
    )
    save_application_event(
        session,
        ApplicationEvent(
            application_id=_persisted_id(app.id),
            kind="behavioral",
            occurred_at=_at(4),
        ),
    )
    application_id = _persisted_id(app.id)
    assert next_sequence(session, application_id, "technical_round") == 2
    assert next_sequence(session, application_id, "behavioral") == 2
    assert next_sequence(session, application_id, "system_design") == 1


def test_delete_returns_false_for_unknown_id():
    session, app = _app()
    assert delete_application_event(session, 999) is False


def test_delete_removes_the_row():
    session, app = _app()
    event = save_application_event(
        session,
        ApplicationEvent(
            application_id=_persisted_id(app.id),
            kind="behavioral",
            occurred_at=_at(3),
        ),
    )
    event_id = _persisted_id(event.id)
    assert delete_application_event(session, event_id) is True
    assert get_application_event(session, event_id) is None
    assert events_for_application(session, _persisted_id(app.id)) == []


def test_events_are_scoped_to_one_application():
    session, app = _app()
    other = Application(job_id=app.job_id)
    session.add(other)
    session.commit()
    session.refresh(other)
    save_application_event(
        session,
        ApplicationEvent(
            application_id=_persisted_id(other.id),
            kind="behavioral",
            occurred_at=_at(3),
        ),
    )
    assert events_for_application(session, _persisted_id(app.id)) == []
