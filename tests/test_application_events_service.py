from datetime import datetime, timezone

import pytest
from sqlmodel import Session, select

import resume_agent.services.application_events as application_events
from resume_agent.db import init_db, make_engine
from resume_agent.services.application_events import (
    EventValidationError,
    create_event,
    delete_event,
    list_events,
    update_event,
)
from resume_agent.tracking.repository import application_for_job
from resume_agent.tracking.tables import Application, ApplicationEvent, Job


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


def test_create_rolls_back_event_and_application_when_advancement_fails(monkeypatch):
    session, job = _job()

    def fail_advance(*_args):
        raise RuntimeError("forced advancement failure")

    monkeypatch.setattr(application_events, "_advance", fail_advance)

    with pytest.raises(RuntimeError, match="forced advancement failure"):
        create_event(
            session,
            job.id,
            {"kind": "application_submitted", "occurred_at": _at(3)},
        )

    assert application_for_job(session, job.id) is None
    assert session.exec(select(ApplicationEvent)).all() == []


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


def test_inserting_an_earlier_round_renumbers_automatic_sequences():
    session, job = _job()
    later = create_event(
        session, job.id, {"kind": "technical_round", "occurred_at": _at(9)}
    )
    earlier = create_event(
        session, job.id, {"kind": "technical_round", "occurred_at": _at(3)}
    )
    session.refresh(later)
    assert (earlier.sequence, later.sequence) == (1, 2)


def test_resequencing_preserves_manual_overrides():
    session, job = _job()
    overridden = create_event(
        session,
        job.id,
        {"kind": "technical_round", "occurred_at": _at(9), "sequence": 7},
    )
    earlier = create_event(
        session, job.id, {"kind": "technical_round", "occurred_at": _at(3)}
    )
    session.refresh(overridden)
    assert (earlier.sequence, overridden.sequence) == (1, 7)


def test_updating_a_round_date_resequences_its_kind():
    session, job = _job()
    first = create_event(
        session, job.id, {"kind": "technical_round", "occurred_at": _at(3)}
    )
    second = create_event(
        session, job.id, {"kind": "technical_round", "occurred_at": _at(9)}
    )

    update_event(session, job.id, second.id, {"occurred_at": _at(1)})

    session.refresh(first)
    session.refresh(second)
    assert (second.sequence, first.sequence) == (1, 2)


def test_changing_kind_resequences_both_groups():
    session, job = _job()
    first = create_event(
        session, job.id, {"kind": "technical_round", "occurred_at": _at(3)}
    )
    moved = create_event(
        session, job.id, {"kind": "technical_round", "occurred_at": _at(9)}
    )

    update_event(session, job.id, first.id, {"kind": "behavioral"})

    session.refresh(first)
    session.refresh(moved)
    assert (first.sequence, moved.sequence) == (1, 1)


def test_deleting_a_round_resequences_later_rounds():
    session, job = _job()
    first = create_event(
        session, job.id, {"kind": "technical_round", "occurred_at": _at(3)}
    )
    second = create_event(
        session, job.id, {"kind": "technical_round", "occurred_at": _at(9)}
    )

    assert delete_event(session, job.id, first.id) is True

    session.refresh(second)
    assert second.sequence == 1


def test_explicit_sequence_overrides_auto_assignment():
    session, job = _job()
    event = create_event(
        session,
        job.id,
        {"kind": "technical_round", "occurred_at": _at(9), "sequence": 3},
    )
    assert event.sequence == 3
    assert event.sequence_override == 3


def test_manual_one_survives_earlier_auto_insert_and_delete():
    session, job = _job()
    manual = create_event(
        session,
        job.id,
        {"kind": "technical_round", "occurred_at": _at(10), "sequence": 1},
    )
    earlier = create_event(
        session, job.id, {"kind": "technical_round", "occurred_at": _at(9)}
    )

    assert manual.sequence == 1
    assert earlier.sequence == 2
    assert delete_event(session, job.id, earlier.id) is True
    session.refresh(manual)
    assert manual.sequence == 1
    assert manual.sequence_override == 1


def test_manual_gap_does_not_push_later_auto_rounds_past_the_gap():
    session, job = _job()
    manual = create_event(
        session,
        job.id,
        {"kind": "technical_round", "occurred_at": _at(9), "sequence": 9},
    )
    first_auto = create_event(
        session, job.id, {"kind": "technical_round", "occurred_at": _at(10)}
    )
    second_auto = create_event(
        session, job.id, {"kind": "technical_round", "occurred_at": _at(11)}
    )

    assert (manual.sequence, first_auto.sequence, second_auto.sequence) == (9, 1, 2)


def test_editing_auto_round_date_and_kind_resequences_both_groups():
    session, job = _job()
    first = create_event(
        session, job.id, {"kind": "technical_round", "occurred_at": _at(9)}
    )
    second = create_event(
        session, job.id, {"kind": "technical_round", "occurred_at": _at(10)}
    )
    behavioral = create_event(
        session, job.id, {"kind": "behavioral", "occurred_at": _at(11)}
    )

    update_event(session, job.id, second.id, {"occurred_at": _at(8)})
    session.refresh(first)
    assert (second.sequence, first.sequence) == (1, 2)

    update_event(session, job.id, second.id, {"kind": "behavioral"})
    session.refresh(first)
    session.refresh(behavioral)
    assert first.sequence == 1
    assert second.sequence == 1
    assert behavioral.sequence == 2


def test_clearing_manual_sequence_restores_automatic_order():
    session, job = _job()
    automatic = create_event(
        session, job.id, {"kind": "technical_round", "occurred_at": _at(10)}
    )
    manual = create_event(
        session,
        job.id,
        {"kind": "technical_round", "occurred_at": _at(9), "sequence": 9},
    )

    updated = update_event(session, job.id, manual.id, {"sequence": None})
    session.refresh(automatic)

    assert updated is not None
    assert updated.sequence_override is None
    assert (updated.sequence, automatic.sequence) == (1, 2)


def test_update_rejects_an_invalid_sequence_at_the_service_boundary():
    session, job = _job()
    event = create_event(
        session, job.id, {"kind": "technical_round", "occurred_at": _at(9)}
    )

    with pytest.raises(EventValidationError, match="positive integer"):
        update_event(session, job.id, event.id, {"sequence": 0})


def test_update_warns_when_sequence_override_collides(caplog):
    session, job = _job()
    create_event(
        session,
        job.id,
        {"kind": "technical_round", "occurred_at": _at(9), "sequence": 3},
    )
    event = create_event(
        session, job.id, {"kind": "technical_round", "occurred_at": _at(10)}
    )

    with caplog.at_level("WARNING"):
        update_event(session, job.id, event.id, {"sequence": 3})

    assert "Duplicate application event key" in caplog.text


def test_update_warns_when_kind_move_collides_with_an_override(caplog):
    session, job = _job()
    create_event(
        session,
        job.id,
        {"kind": "behavioral", "occurred_at": _at(9), "sequence": 4},
    )
    event = create_event(
        session,
        job.id,
        {"kind": "technical_round", "occurred_at": _at(10), "sequence": 4},
    )

    with caplog.at_level("WARNING"):
        update_event(session, job.id, event.id, {"kind": "behavioral"})

    assert "Duplicate application event key" in caplog.text


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
            {
                "kind": "technical_round",
                "occurred_at": _at(3),
                "custom_label": "not custom",
            },
            "custom_label",
        ),
        (
            {
                "kind": "technical_round",
                "occurred_at": _at(3),
                "platform": "zoom",
                "platform_other": "not other",
            },
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


def test_update_rolls_back_event_and_status_when_advancement_fails(monkeypatch):
    session, job = _job()
    event = create_event(
        session, job.id, {"kind": "recruiter_screen", "occurred_at": _at(3)}
    )
    original_status = application_for_job(session, job.id).status

    def fail_advance(*_args):
        raise RuntimeError("forced advancement failure")

    monkeypatch.setattr(application_events, "_advance", fail_advance)

    with pytest.raises(RuntimeError, match="forced advancement failure"):
        update_event(
            session,
            job.id,
            event.id,
            {"kind": "offer_received", "occurred_at": _at(20)},
        )

    session.refresh(event)
    assert event.kind == "recruiter_screen"
    assert application_for_job(session, job.id).status == original_status


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


def test_deleting_an_auto_numbered_round_closes_the_sequence_gap():
    session, job = _job()
    first = create_event(
        session, job.id, {"kind": "technical_round", "occurred_at": _at(9)}
    )
    middle = create_event(
        session, job.id, {"kind": "technical_round", "occurred_at": _at(10)}
    )
    create_event(session, job.id, {"kind": "technical_round", "occurred_at": _at(11)})

    assert delete_event(session, job.id, middle.id) is True

    rounds = [
        event
        for event in list_events(session, job.id)
        if event.kind == "technical_round"
    ]
    assert rounds[0].id == first.id
    assert [event.sequence for event in rounds] == [1, 2]


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


def test_create_event_and_status_advance_commit_atomically(monkeypatch):
    session, job = _job()

    def fail_advance(*_args):
        raise RuntimeError("status write failed")

    monkeypatch.setattr(application_events, "_advance", fail_advance)
    with pytest.raises(RuntimeError, match="status write failed"):
        create_event(
            session,
            job.id,
            {"kind": "application_submitted", "occurred_at": _at(3)},
        )
    session.rollback()

    assert session.exec(select(Application)).all() == []
    assert session.exec(select(ApplicationEvent)).all() == []
