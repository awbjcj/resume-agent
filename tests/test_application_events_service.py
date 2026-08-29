from datetime import datetime, timezone

import pytest
from sqlmodel import Session

from resume_agent.db import init_db, make_engine
from resume_agent.services.application_events import (
    EventValidationError,
    create_event,
    delete_event,
    list_events,
    update_event,
)
from resume_agent.tracking.repository import application_for_job
from resume_agent.tracking.tables import Job


def _job():
    engine = make_engine("sqlite://")
    init_db(engine)
    session = Session(engine)
    job = Job(source="test", company="Acme", title="SWE")
    session.add(job)
    session.commit()
    session.refresh(job)
    return session, job


def _at(day):
    return datetime(2026, 3, day, 12, 0, tzinfo=timezone.utc)


def test_create_makes_the_application_row_when_absent():
    session, job = _job()
    create_event(
        session, job.id, {"kind": "application_submitted", "occurred_at": _at(3)}
    )
    assert application_for_job(session, job.id) is not None


def test_create_advances_status_through_the_progression():
    session, job = _job()
    create_event(
        session, job.id, {"kind": "application_submitted", "occurred_at": _at(3)}
    )
    assert application_for_job(session, job.id).status == "submitted"
    create_event(session, job.id, {"kind": "technical_round", "occurred_at": _at(9)})
    assert application_for_job(session, job.id).status == "interview"


def test_a_late_logged_earlier_stage_never_demotes():
    session, job = _job()
    create_event(session, job.id, {"kind": "offer_received", "occurred_at": _at(20)})
    create_event(session, job.id, {"kind": "recruiter_screen", "occurred_at": _at(3)})
    assert application_for_job(session, job.id).status == "offer"


def test_rejected_event_is_terminal_even_from_offer():
    session, job = _job()
    create_event(session, job.id, {"kind": "offer_received", "occurred_at": _at(20)})
    create_event(session, job.id, {"kind": "rejected", "occurred_at": _at(22)})
    assert application_for_job(session, job.id).status == "rejected"


def test_result_rejected_on_a_round_does_not_kill_the_application():
    session, job = _job()
    create_event(
        session,
        job.id,
        {"kind": "technical_round", "occurred_at": _at(9), "result": "rejected"},
    )
    assert application_for_job(session, job.id).status == "interview"


def test_custom_events_never_move_status():
    session, job = _job()
    create_event(session, job.id, {"kind": "custom", "custom_label": "sent thank-you"})
    assert application_for_job(session, job.id).status == "ready"


def test_sequence_auto_increments_per_kind():
    session, job = _job()
    first = create_event(
        session, job.id, {"kind": "technical_round", "occurred_at": _at(9)}
    )
    second = create_event(
        session, job.id, {"kind": "technical_round", "occurred_at": _at(11)}
    )
    assert (first.sequence, second.sequence) == (1, 2)


def test_explicit_sequence_overrides_auto_assignment():
    session, job = _job()
    event = create_event(
        session,
        job.id,
        {"kind": "technical_round", "occurred_at": _at(9), "sequence": 3},
    )
    assert event.sequence == 3


@pytest.mark.parametrize(
    "payload,fragment",
    [
        ({"kind": "not_a_kind", "occurred_at": _at(3)}, "kind"),
        ({"kind": "technical_round"}, "occurred_at"),
        ({"kind": "custom"}, "custom_label"),
        (
            {"kind": "technical_round", "occurred_at": _at(3), "platform": "other"},
            "platform_other",
        ),
        (
            {"kind": "technical_round", "occurred_at": _at(3), "modality": "teleport"},
            "modality",
        ),
        (
            {"kind": "technical_round", "occurred_at": _at(3), "result": "vibes"},
            "result",
        ),
    ],
)
def test_validation_rejects_bad_payloads(payload, fragment):
    session, job = _job()
    with pytest.raises(EventValidationError) as excinfo:
        create_event(session, job.id, payload)
    assert fragment in str(excinfo.value)


def test_custom_events_may_omit_a_date():
    session, job = _job()
    event = create_event(
        session, job.id, {"kind": "custom", "custom_label": "referral ping"}
    )
    assert event.occurred_at is None


def test_update_changes_fields_and_can_advance_status():
    session, job = _job()
    event = create_event(
        session, job.id, {"kind": "recruiter_screen", "occurred_at": _at(3)}
    )
    updated = update_event(
        session, job.id, event.id, {"kind": "offer_received", "occurred_at": _at(20)}
    )
    assert updated.kind == "offer_received"
    assert application_for_job(session, job.id).status == "offer"


def test_update_returns_none_for_an_event_on_another_job():
    session, job = _job()
    other = Job(source="test")
    session.add(other)
    session.commit()
    session.refresh(other)
    event = create_event(
        session, other.id, {"kind": "behavioral", "occurred_at": _at(3)}
    )
    assert update_event(session, job.id, event.id, {"notes": "x"}) is None


def test_delete_does_not_move_status_back():
    session, job = _job()
    event = create_event(
        session, job.id, {"kind": "technical_round", "occurred_at": _at(9)}
    )
    assert delete_event(session, job.id, event.id) is True
    assert application_for_job(session, job.id).status == "interview"


def test_list_events_returns_timeline_order():
    session, job = _job()
    create_event(session, job.id, {"kind": "online_assessment", "occurred_at": _at(9)})
    create_event(
        session, job.id, {"kind": "application_submitted", "occurred_at": _at(3)}
    )
    assert [e.kind for e in list_events(session, job.id)] == [
        "application_submitted",
        "online_assessment",
    ]
