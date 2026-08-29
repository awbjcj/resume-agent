import pytest
from pydantic import ValidationError

from resume_agent.discovery.scout_store import (
    ManualSourceConfirmation,
    ScoutProposal,
    ScoutProposalChangedError,
    ScoutTurnRecord,
    SourcePayload,
    TermPayload,
    active_session,
    apply_turn_delta,
    create_session_from_turn,
    end_session,
    load_session,
    replace_pending_source_resolution,
    set_proposal_status,
)
from resume_agent.discovery.source_resolution.models import (
    CompanySourceResolution,
    SourceEvidence,
)


def source(company: str) -> ScoutProposal:
    return ScoutProposal(
        kind="source",
        source=SourcePayload(company=company, url=f"https://{company}.example/jobs"),
    )


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


def _verified_resolution(url: str) -> CompanySourceResolution:
    return CompanySourceResolution(
        company="Acme",
        requested_url="https://old.example/jobs",
        canonical_board_url=url,
        ats="lever",
        token="acme",
        role_count=3,
        status="verified",
        reason_code="VERIFIED_PROVIDER_METADATA",
        evidence=[
            SourceEvidence(
                kind="provider_company",
                source_url=url,
                summary="Provider metadata identifies Acme.",
            )
        ],
    )


def test_legacy_source_payload_defaults_resolution_fields():
    payload = SourcePayload.model_validate(
        {"company": "Acme", "url": "https://acme.test"}
    )
    assert payload.resolution_status is None
    assert payload.evidence == []
    assert payload.searched_families == []


def test_replacement_requires_the_pending_exact_url(tmp_path):
    create_session_from_turn(
        tmp_path,
        "s1",
        goal="AI infra",
        user_text="AI infra",
        scout_turn=ScoutTurnRecord(role="scout", text="First"),
        proposals=[
            ScoutProposal(
                kind="source",
                source=SourcePayload(company="Acme", url="https://old.example/jobs"),
            )
        ],
    )
    with pytest.raises(ScoutProposalChangedError, match="source URL changed"):
        replace_pending_source_resolution(
            tmp_path,
            "s1",
            "p1",
            expected_url="https://stale.example/jobs",
            resolution=_verified_resolution("https://new.example/jobs"),
        )
    assert (
        load_session(tmp_path, "s1")["proposals"][0]["source"]["url"]
        == "https://old.example/jobs"
    )


def test_added_override_persists_exact_confirmation(tmp_path):
    create_session_from_turn(
        tmp_path,
        "s1",
        goal="AI infra",
        user_text="AI infra",
        scout_turn=ScoutTurnRecord(role="scout", text="First"),
        proposals=[
            ScoutProposal(
                kind="source",
                source=SourcePayload(
                    company="Acme",
                    url="https://jobs.lever.co/acme",
                    ats="lever",
                    resolution_status="unverified",
                    resolution_reason="OWNERSHIP_NOT_PROVEN",
                ),
                check="unverified",
            )
        ],
    )
    confirmation = ManualSourceConfirmation(
        company="Acme",
        url="https://jobs.lever.co/acme",
        ats="lever",
        resolution_reason="OWNERSHIP_NOT_PROVEN",
        confirmed_at="2026-08-14T12:00:00Z",
    )
    set_proposal_status(tmp_path, "s1", "p1", "added", confirmation=confirmation)
    row = load_session(tmp_path, "s1")["proposals"][0]
    assert row["manual_confirmation"]["url"] == "https://jobs.lever.co/acme"


def test_replacement_projects_resolution_and_preserves_proposal_company(tmp_path):
    create_session_from_turn(
        tmp_path,
        "s1",
        goal="AI infra",
        user_text="AI infra",
        scout_turn=ScoutTurnRecord(role="scout", text="First"),
        proposals=[
            ScoutProposal(
                kind="source",
                source=SourcePayload(company="Acme", url="https://old.example/jobs"),
                manual_confirmation=ManualSourceConfirmation(
                    company="Acme",
                    url="https://old.example/jobs",
                    resolution_reason="OWNERSHIP_NOT_PROVEN",
                    confirmed_at="2026-08-14T12:00:00Z",
                ),
            )
        ],
    )
    resolution = _verified_resolution("https://jobs.lever.co/acme")
    resolution = resolution.model_copy(update={"company": "A Different Company"})

    updated = replace_pending_source_resolution(
        tmp_path,
        "s1",
        "p1",
        expected_url="https://old.example/jobs",
        resolution=resolution,
    )

    row = updated["proposals"][0]
    assert row["id"] == "p1"
    assert row["check"] == "validated"
    assert row["source"]["company"] == "Acme"
    assert row["source"]["url"] == "https://jobs.lever.co/acme"
    assert row["source"]["requested_url"] == "https://old.example/jobs"
    assert row["manual_confirmation"] is None
