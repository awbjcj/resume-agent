import pytest

from resume_tailor_harness.tracking.status_rules import (
    PROGRESSION,
    TERMINAL,
    advance_application_status,
)


@pytest.mark.parametrize(
    "current,implied,expected",
    [
        ("ready", "submitted", "submitted"),
        ("submitted", "interview", "interview"),
        ("interview", "offer", "offer"),
        # Forward-only: a late-logged earlier stage never demotes.
        ("offer", "interview", "offer"),
        ("interview", "submitted", "interview"),
        ("submitted", "submitted", "submitted"),
    ],
)
def test_progression_advances_forward_only(current, implied, expected):
    assert advance_application_status(current, implied) == expected


@pytest.mark.parametrize("current", ["ready", "submitted", "interview", "offer"])
def test_terminal_is_reachable_from_every_progression_state(current):
    assert advance_application_status(current, "rejected") == "rejected"
    assert advance_application_status(current, "closed") == "closed"


def test_offer_to_rejected_works_because_offers_get_rescinded():
    assert advance_application_status("offer", "rejected") == "rejected"


def test_terminal_states_are_sticky_against_progression():
    assert advance_application_status("rejected", "interview") == "rejected"
    assert advance_application_status("closed", "offer") == "closed"


def test_terminal_can_be_replaced_by_the_other_terminal():
    assert advance_application_status("rejected", "closed") == "closed"


def test_vocabulary_shape():
    assert PROGRESSION == ("ready", "submitted", "interview", "offer")
    assert TERMINAL == frozenset({"rejected", "closed"})


def test_unknown_implied_status_is_a_no_op():
    assert advance_application_status("submitted", "nonsense") == "submitted"
