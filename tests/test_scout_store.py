import pytest
from pydantic import ValidationError

from resume_agent.discovery.scout_store import (
    ScoutProposal,
    ScoutTurnRecord,
    SourcePayload,
    TermPayload,
    active_session,
    apply_turn_delta,
    create_session_from_turn,
    end_session,
    load_session,
    set_proposal_status,
)


def source(company: str) -> ScoutProposal:
    return ScoutProposal(kind="source", source=SourcePayload(company=company, url=f"https://{company}.example/jobs"))


def term(value: str) -> ScoutProposal:
    return ScoutProposal(kind="search_term", term=TermPayload(value=value))


def test_proposal_requires_exactly_one_matching_payload():
    with pytest.raises(ValidationError):
        ScoutProposal(kind="source")
    with pytest.raises(ValidationError):
        ScoutProposal(kind="source", source=SourcePayload(), term=TermPayload())
    with pytest.raises(ValidationError):
        ScoutProposal(kind="search_term", source=SourcePayload(company="Acme"))


def test_create_and_append_assign_ids_under_lock(tmp_path):
    first = create_session_from_turn(
        tmp_path,
        "abc",
        goal="AI infra",
        user_text="AI infra",
        scout_turn=ScoutTurnRecord(role="scout", text="First"),
        proposals=[source("modal")],
    )
    second = apply_turn_delta(
        tmp_path,
        "abc",
        user_text="smaller",
        scout_turn=ScoutTurnRecord(role="scout", text="Second"),
        proposals=[term("inference serving")],
        goal_update="seed-stage AI infra",
    )
    assert [row["id"] for row in first["proposals"]] == ["p1"]
    assert [row["id"] for row in second["proposals"]] == ["p1", "p2"]
    assert second["turns"][-1]["proposal_ids"] == ["p2"]
    assert second["goal"] == "seed-stage AI infra"
    assert load_session(tmp_path, "abc") == second


def test_one_active_session_and_late_resolution_after_end(tmp_path):
    create_session_from_turn(
        tmp_path,
        "one",
        goal="AI infra",
        user_text="AI infra",
        scout_turn=ScoutTurnRecord(role="scout", text="First"),
        proposals=[source("modal")],
    )
    with pytest.raises(ValueError, match="active session"):
        create_session_from_turn(
            tmp_path,
            "two",
            goal="other",
            user_text="other",
            scout_turn=ScoutTurnRecord(role="scout", text="Other"),
            proposals=[],
        )
    ended = end_session(tmp_path, "one", "Recap")
    assert ended["status"] == "ended"
    assert active_session(tmp_path) is None
    resolved = set_proposal_status(tmp_path, "one", "p1", "dismissed", reason="too big")
    assert resolved["proposals"][0]["dismiss_reason"] == "too big"
    with pytest.raises(ValueError, match="session ended"):
        apply_turn_delta(
            tmp_path,
            "one",
            user_text="more",
            scout_turn=ScoutTurnRecord(role="scout", text="No"),
            proposals=[],
        )
