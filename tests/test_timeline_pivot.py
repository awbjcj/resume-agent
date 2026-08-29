from datetime import datetime, timezone

from sqlmodel import Session

from resume_agent.db import init_db, make_engine
from resume_agent.tracking.timeline_pivot import build_pivot
from resume_agent.tracking.tables import Application, ApplicationEvent, Job


def _persisted_id(value: int | None) -> int:
    assert value is not None
    return value


def _at(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 3, day, hour, tzinfo=timezone.utc)


def _session() -> Session:
    engine = make_engine("sqlite://")
    init_db(engine)
    return Session(engine)


def _application(session: Session, company: str = "Acme", status: str = "interview"):
    job = Job(source="greenhouse", company=company, title="SWE")
    session.add(job)
    session.commit()
    session.refresh(job)
    app = Application(job_id=_persisted_id(job.id), status=status)
    session.add(app)
    session.commit()
    session.refresh(app)
    return job, app


def _event(
    session: Session, app: Application, kind: str, day: int | None = None, **over
):
    session.add(
        ApplicationEvent(
            application_id=_persisted_id(app.id),
            kind=kind,
            occurred_at=_at(day) if day else None,
            **over,
        )
    )
    session.commit()


def test_pivot_keys_cells_and_sorts_recent_first():
    session = _session()
    _, old = _application(session, "Old")
    _event(session, old, "application_submitted", 3)
    _, recent = _application(session, "Recent")
    _event(session, recent, "recruiter_screen", 20)
    table = build_pivot(session)
    assert [row.company for row in table.rows] == ["Recent", "Old"]
    assert table.rows[1].cells["application_submitted"].occurred_at == _at(3)


def test_technical_round_columns_use_stored_sequence_and_report_overflow():
    session = _session()
    job, app = _application(session)
    _event(session, app, "technical_round", 12, sequence=3)
    _event(session, app, "technical_round", 10, sequence=1)
    _event(session, app, "technical_round", 11, sequence=2)
    _event(session, app, "technical_round", 15, sequence=7)
    table = build_pivot(session, max_technical_rounds=3)
    row = table.rows[0]
    assert row.cells["technical_round_2"].occurred_at == _at(11)
    assert table.technical_round_columns == 3
    assert table.overflow_by_job[_persisted_id(job.id)] == 1


def test_duplicate_technical_round_key_is_visible_as_overflow(caplog):
    session = _session()
    job, app = _application(session)
    _event(session, app, "technical_round", 10, sequence=2)
    _event(session, app, "technical_round", 11, sequence=2)

    table = build_pivot(session)

    assert table.overflow_by_job[_persisted_id(job.id)] == 1
    assert "Duplicate pivot cell" in caplog.text


def test_uncapped_pivot_retains_every_round_and_full_event_rows():
    session = _session()
    _, app = _application(session)
    for sequence in range(1, 10):
        _event(session, app, "technical_round", sequence, sequence=sequence)
    table = build_pivot(session, max_technical_rounds=None)
    assert table.technical_round_columns == 9
    assert "technical_round_9" in table.rows[0].cells
    assert len(table.rows[0].events) == 9


def test_full_event_rows_tie_break_equal_dates_by_created_at_then_id():
    session = _session()
    _, app = _application(session)
    shared_time = _at(12)
    later_created = ApplicationEvent(
        application_id=_persisted_id(app.id),
        kind="recruiter_screen",
        occurred_at=shared_time,
        sequence=1,
        created_at=_at(14),
    )
    earlier_created = ApplicationEvent(
        application_id=_persisted_id(app.id),
        kind="technical_round",
        occurred_at=shared_time,
        sequence=9,
        created_at=_at(13),
    )
    session.add_all([later_created, earlier_created])
    session.commit()

    events = build_pivot(session).rows[0].events

    assert [event.kind for event in events] == ["technical_round", "recruiter_screen"]


def test_custom_offer_deadline_and_latest_offer_are_preserved():
    session = _session()
    _, app = _application(session, status="offer")
    _event(session, app, "custom", 3, custom_label="referral ping")
    _event(session, app, "offer_received", 20, comp_base=180_000, comp_currency="USD")
    _event(
        session,
        app,
        "offer_received",
        25,
        sequence=2,
        comp_base=195_000,
        comp_signing=25_000,
        comp_currency="USD",
    )
    _event(session, app, "offer_deadline", 27)
    table = build_pivot(session)
    row = table.rows[0]
    assert row.custom_count == 1
    assert row.total_comp == 220_000
    assert row.comp_currency == "USD"
    assert row.offer_deadline == _at(27)
    assert table.overflow_by_job == {}


def test_archived_jobs_are_excluded_and_undated_applications_remain():
    session = _session()
    job, app = _application(session, "Archived")
    _event(session, app, "recruiter_screen", 3)
    job.archived_at = _at(4)
    session.add(job)
    session.commit()
    _application(session, "Undated", status="ready")
    table = build_pivot(session)
    assert [row.company for row in table.rows] == ["Undated"]
    assert table.rows[0].cells == {}
