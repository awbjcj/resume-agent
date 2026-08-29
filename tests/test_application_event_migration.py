from datetime import datetime, timezone

from sqlalchemy import text
from sqlmodel import Session, select

from resume_agent.db import init_db, make_engine
from resume_agent.tracking.migrate import (
    ensure_application_event_sequence_override_column,
    ensure_application_submitted_events,
)
from resume_agent.tracking.tables import Application, ApplicationEvent, Job


def _persisted_id(value: int | None) -> int:
    assert value is not None
    return value


def _seed(submitted_at):
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        job = Job(source="test", company="Acme")
        session.add(job)
        session.commit()
        session.refresh(job)
        session.add(
            Application(
                job_id=_persisted_id(job.id),
                status="submitted",
                submitted_at=submitted_at,
            )
        )
        session.commit()
    return engine


def test_backfills_one_event_per_submitted_application():
    engine = _seed(datetime(2026, 3, 3, 12, 0, tzinfo=timezone.utc))
    ensure_application_submitted_events(engine)
    with Session(engine) as session:
        events = session.exec(select(ApplicationEvent)).all()
    assert len(events) == 1
    assert events[0].kind == "application_submitted"
    assert events[0].all_day is True
    assert events[0].result == "advanced"
    assert events[0].source == "migration"


def test_is_idempotent():
    engine = _seed(datetime(2026, 3, 3, 12, 0, tzinfo=timezone.utc))
    ensure_application_submitted_events(engine)
    ensure_application_submitted_events(engine)
    with Session(engine) as session:
        assert len(session.exec(select(ApplicationEvent)).all()) == 1


def test_skips_applications_with_no_submitted_at():
    engine = _seed(None)
    ensure_application_submitted_events(engine)
    with Session(engine) as session:
        assert session.exec(select(ApplicationEvent)).all() == []


def test_does_not_synthesize_events_from_status_alone():
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        job = Job(source="test")
        session.add(job)
        session.commit()
        session.refresh(job)
        session.add(
            Application(
                job_id=_persisted_id(job.id), status="interview", submitted_at=None
            )
        )
        session.commit()
    ensure_application_submitted_events(engine)
    with Session(engine) as session:
        assert session.exec(select(ApplicationEvent)).all() == []


def test_init_db_runs_the_backfill():
    engine = _seed(datetime(2026, 3, 3, 12, 0, tzinfo=timezone.utc))
    init_db(engine)  # second call must backfill and stay idempotent
    with Session(engine) as session:
        assert len(session.exec(select(ApplicationEvent)).all()) == 1


def test_adds_nullable_sequence_override_to_a_legacy_event_table():
    engine = make_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE application_events ("
                "id INTEGER PRIMARY KEY, sequence INTEGER NOT NULL DEFAULT 1)"
            )
        )
        conn.execute(
            text("INSERT INTO application_events (id, sequence) VALUES (1, 3), (2, 9)")
        )

    ensure_application_event_sequence_override_column(engine)

    with engine.begin() as conn:
        columns = {
            row[1]: row
            for row in conn.execute(text("PRAGMA table_info(application_events)"))
        }
        migrated = conn.execute(
            text(
                "SELECT sequence, sequence_override FROM application_events ORDER BY id"
            )
        ).fetchall()
        conn.execute(
            text(
                "INSERT INTO application_events (id, sequence, sequence_override) "
                "VALUES (3, 2, NULL)"
            )
        )
    ensure_application_event_sequence_override_column(engine)
    with engine.begin() as conn:
        new_row_override = conn.execute(
            text("SELECT sequence_override FROM application_events WHERE id = 3")
        ).scalar_one()
    assert "sequence_override" in columns
    assert columns["sequence_override"][3] == 0
    assert migrated == [(3, 3), (9, 9)]
    assert new_row_override is None


def test_upgrades_boolean_sequence_override_marker_without_freezing_auto_rows():
    engine = make_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE application_events ("
                "id INTEGER PRIMARY KEY, sequence INTEGER NOT NULL DEFAULT 1, "
                "sequence_overridden BOOLEAN NOT NULL DEFAULT 0)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO application_events "
                "(id, sequence, sequence_overridden) "
                "VALUES (1, 3, 0), (2, 9, 1)"
            )
        )

    ensure_application_event_sequence_override_column(engine)

    with engine.begin() as conn:
        migrated = conn.execute(
            text("SELECT sequence_override FROM application_events ORDER BY id")
        ).fetchall()
    assert migrated == [(None,), (9,)]
