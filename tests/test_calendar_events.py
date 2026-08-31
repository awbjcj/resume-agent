from datetime import datetime, timedelta, timezone

from sqlmodel import Session

from resume_tailor_harness.calendar.events import entries_for_upcoming, entry_for_event
from resume_tailor_harness.db import init_db, make_engine
from resume_tailor_harness.tracking.tables import Application, ApplicationEvent, Job

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)


def _require_id(value: int | None) -> int:
    assert value is not None
    return value


def _event(**over) -> ApplicationEvent:
    values = {
        "id": 1,
        "application_id": 7,
        "kind": "technical_round",
        "sequence": 2,
        "occurred_at": datetime(2026, 3, 9, 19, 0, tzinfo=timezone.utc),
        "all_day": False,
        "duration_minutes": 90,
        "platform": "zoom",
        "location_or_link": "https://zoom.us/j/123",
        "interviewers": "Dana Vale",
    }
    values.update(over)
    return ApplicationEvent(**values)


def _job() -> Job:
    return Job(id=42, source="test", company="Acme", title="Senior SWE")


def test_event_mapping_preserves_actionable_calendar_details() -> None:
    entry = entry_for_event(_event(notes="LRU cache"), _job())
    assert entry.summary == "Technical round 2 — Acme"
    assert entry.end is not None
    assert entry.end - entry.start == timedelta(minutes=90)
    assert entry.url == entry.location == "https://zoom.us/j/123"
    assert entry.description is not None
    assert "Dana Vale" in entry.description
    assert "Zoom" in entry.description
    assert "LRU cache" in entry.description
    assert entry.uid == "application-event-1@resume-tailor-harness"
    assert entry.alarm_minutes_before == 60


def test_all_day_event_has_no_alarm_or_duration_end() -> None:
    entry = entry_for_event(_event(all_day=True), _job())
    assert entry.end is None
    assert entry.alarm_minutes_before is None


def test_street_address_is_a_location_not_a_url() -> None:
    entry = entry_for_event(_event(location_or_link="1 Main St, Austin TX"), _job())
    assert entry.location == "1 Main St, Austin TX"
    assert entry.url is None


def test_upcoming_bulk_calendar_excludes_past_cancelled_and_terminal_rows() -> None:
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        for index, status in enumerate(("interview", "rejected"), start=1):
            job = Job(source="test", company=f"Company {index}", title="SWE")
            session.add(job)
            session.commit()
            session.refresh(job)
            application = Application(job_id=_require_id(job.id), status=status)
            session.add(application)
            session.commit()
            session.refresh(application)
            session.add_all(
                [
                    ApplicationEvent(
                        application_id=_require_id(application.id),
                        kind="technical_round",
                        occurred_at=NOW + timedelta(days=3),
                    ),
                    ApplicationEvent(
                        application_id=_require_id(application.id),
                        kind="recruiter_screen",
                        occurred_at=NOW - timedelta(days=1),
                    ),
                    ApplicationEvent(
                        application_id=_require_id(application.id),
                        kind="behavioral",
                        occurred_at=NOW + timedelta(days=2),
                        result="cancelled",
                    ),
                ]
            )
            session.commit()
        entries = entries_for_upcoming(session, now=NOW)
    assert len(entries) == 1
    assert "Company 1" in entries[0].summary
