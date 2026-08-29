from datetime import datetime, timezone

from sqlmodel import Session

from resume_agent.db import init_db, make_engine
from resume_agent.tracking.funnel import _sequences, stage_cycle_times, stage_flows
from resume_agent.tracking.tables import Application, ApplicationEvent, Job


def _at(day: int, hour: int = 12) -> datetime:
    return datetime(2026, 3, day, hour, tzinfo=timezone.utc)


def _session() -> Session:
    engine = make_engine("sqlite://")
    init_db(engine)
    return Session(engine)


def _app(session: Session, status: str = "interview") -> Application:
    job = Job(source="test", company="Acme", title="SWE")
    session.add(job)
    session.commit()
    session.refresh(job)
    app = Application(job_id=job.id, status=status)
    session.add(app)
    session.commit()
    session.refresh(app)
    return app


def _event(session: Session, app: Application, kind: str, day: int, hour: int = 12, **over):
    session.add(
        ApplicationEvent(
            application_id=app.id,
            kind=kind,
            occurred_at=_at(day, hour),
            **over,
        )
    )
    session.commit()


def _edge(edges, source: str, target: str) -> int:
    return next((edge.count for edge in edges if (edge.source, edge.target) == (source, target)), 0)


def test_stage_flows_accumulate_and_emit_distinct_exits():
    session = _session()
    for status in ("interview", "rejected"):
        app = _app(session, status)
        _event(session, app, "application_submitted", 3)
        _event(session, app, "recruiter_screen", 5)
    ghosted = _app(session, "submitted")
    _event(session, ghosted, "application_submitted", 3, result="no_response")
    edges = stage_flows(session)
    assert _edge(edges, "application_submitted", "recruiter_screen") == 2
    assert _edge(edges, "recruiter_screen", "rejected") == 1
    assert _edge(edges, "application_submitted", "no_response") == 1


def test_custom_events_never_enter_funnel_or_cycle_times():
    session = _session()
    app = _app(session)
    _event(session, app, "application_submitted", 3)
    _event(session, app, "custom", 4, custom_label="coffee")
    _event(session, app, "recruiter_screen", 5)
    edges = stage_flows(session)
    assert _edge(edges, "application_submitted", "recruiter_screen") == 1
    assert all("custom" not in (edge.source, edge.target) for edge in edges)


def test_cycle_time_is_fractional_median_with_sample_size():
    session = _session()
    for end_hour in (18, 20, 22):
        app = _app(session)
        _event(session, app, "application_submitted", 1, hour=12)
        _event(session, app, "recruiter_screen", 2, hour=end_hour)
    entry = stage_cycle_times(session)[0]
    assert entry.median_days == 4 / 3
    assert entry.sample_size == 3


def test_out_of_order_dates_cannot_make_negative_gaps():
    session = _session()
    app = _app(session)
    _event(session, app, "recruiter_screen", 3)
    _event(session, app, "application_submitted", 9)
    assert all(item.median_days >= 0 for item in stage_cycle_times(session))


def test_equal_dates_tie_break_by_created_at_instead_of_stage_sequence():
    session = _session()
    app = _app(session)
    shared_time = _at(3)
    session.add_all(
        [
            ApplicationEvent(
                application_id=app.id,
                kind="recruiter_screen",
                occurred_at=shared_time,
                sequence=1,
                created_at=_at(5),
            ),
            ApplicationEvent(
                application_id=app.id,
                kind="technical_round",
                occurred_at=shared_time,
                sequence=9,
                created_at=_at(4),
            ),
        ]
    )
    session.commit()

    assert [event.kind for event in _sequences(session)[0][1]] == [
        "technical_round",
        "recruiter_screen",
    ]


def test_repeatable_and_out_of_order_stages_do_not_create_sankey_cycles():
    session = _session()
    app = _app(session)
    _event(session, app, "technical_round", 1, sequence=1)
    _event(session, app, "technical_round", 2, sequence=2)
    _event(session, app, "recruiter_screen", 3)

    edges = stage_flows(session)

    assert _edge(edges, "technical_round", "technical_round") == 0
    assert _edge(edges, "technical_round", "recruiter_screen") == 0


def test_non_monotonic_history_projects_to_one_connected_milestone_path():
    session = _session()
    app = _app(session, "rejected")
    _event(session, app, "application_submitted", 1)
    _event(session, app, "technical_round", 2)
    _event(session, app, "technical_round", 3)
    _event(session, app, "recruiter_screen", 4)
    _event(session, app, "offer_received", 5)

    edges = stage_flows(session)
    cycles = stage_cycle_times(session)

    assert [(edge.source, edge.target, edge.count) for edge in edges] == [
        ("application_submitted", "technical_round", 1),
        ("offer_received", "rejected", 1),
        ("technical_round", "offer_received", 1),
    ]
    assert [(row.from_kind, row.to_kind) for row in cycles] == [
        ("application_submitted", "technical_round"),
        ("technical_round", "offer_received"),
    ]


def test_archived_jobs_and_empty_database_are_ignored():
    session = _session()
    app = _app(session)
    job = session.get(Job, app.job_id)
    assert job is not None
    _event(session, app, "application_submitted", 3)
    job.archived_at = _at(4)
    session.add(job)
    session.commit()
    assert stage_flows(session) == []
    assert stage_cycle_times(session) == []
