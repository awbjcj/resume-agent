import json

import pytest

from resume_agent.discovery import scout
from resume_agent.discovery.scout import (
    ProposalRejected,
    ScoutProposalDraft,
    ScoutTurnDraft,
    normalize_recap,
    normalize_turn,
)
from resume_agent.sessions.turns import TurnRejected


def test_normalize_retries_integrity_then_drops_all_proposals():
    turn = ScoutTurnDraft(
        message="I found one lead.",
        goal_update="seed-stage AI infrastructure",
        proposals=[ScoutProposalDraft(kind="source")],
    )

    with pytest.raises(ProposalRejected, match="exactly one payload"):
        normalize_turn(turn, {"proposals": []}, strict=True)

    degraded = normalize_turn(turn, {"proposals": []}, strict=False)
    assert degraded.message == "I found one lead."
    assert degraded.goal_update == "seed-stage AI infrastructure"
    assert degraded.proposals == []
    assert degraded.notice == scout.PROPOSALS_OMITTED_NOTICE


@pytest.mark.parametrize(
    "proposal",
    [
        {"kind": "unknown", "term": {"value": "python"}},
        {"kind": "search_term", "term": {"value": "python"}, "disposition": "avoid"},
        {"kind": "source", "source": {"company": "Acme", "url": "file:///etc/passwd"}},
        {"kind": "search_term", "term": {"value": "principal", "term_kind": "seniority"}},
        {"kind": "search_term", "term": {"value": "python"}, "fit_score": 101},
    ],
)
def test_normalize_classifies_semantically_bad_drafts(proposal):
    turn = ScoutTurnDraft.model_validate({"message": "Found it", "proposals": [proposal]})
    with pytest.raises((ProposalRejected, TurnRejected)):
        normalize_turn(turn, {"proposals": []})


def test_positive_sources_and_all_citations_require_http_urls():
    bad = ScoutTurnDraft.model_validate(
        {
            "message": "Found it",
            "proposals": [
                {
                    "kind": "source",
                    "source": {"company": "Acme", "url": "https://acme.example/jobs"},
                    "citations": [{"url": "javascript:alert(1)", "title": "bad"}],
                }
            ],
        }
    )
    with pytest.raises(ProposalRejected, match="citation"):
        normalize_turn(bad, {"proposals": []})


def test_avoid_source_needs_company_and_evidence_but_not_careers_url():
    turn = ScoutTurnDraft.model_validate(
        {
            "message": "One company is a poor fit.",
            "proposals": [
                {
                    "kind": "source",
                    "source": {"company": "Acme"},
                    "disposition": "avoid",
                    "citations": [{"url": "https://news.example/acme", "title": "Layoffs"}],
                }
            ],
        }
    )
    validated = normalize_turn(turn, {"proposals": []})
    proposal = validated.proposals[0]
    assert proposal.source is not None
    assert proposal.source.company == "Acme"


def test_turn_and_pending_caps_are_structural():
    rows = [{"kind": "search_term", "term": {"value": f"term-{index}"}} for index in range(9)]
    with pytest.raises(TurnRejected, match="at most 8"):
        normalize_turn(
            ScoutTurnDraft.model_validate({"message": "Too many", "proposals": rows}),
            {"proposals": []},
        )

    pending = [{"status": "pending"}] * 40
    with pytest.raises(TurnRejected, match="40 pending"):
        normalize_turn(
            ScoutTurnDraft.model_validate({"message": "One more", "proposals": [rows[0]]}),
            {"proposals": pending},
        )


def test_recap_rejects_proposals_and_goal_updates():
    with pytest.raises(TurnRejected):
        normalize_recap(
            ScoutTurnDraft.model_validate(
                {
                    "kind": "recap",
                    "message": "Done",
                    "goal_update": "changed",
                    "proposals": [{"kind": "search_term", "term": {"value": "python"}}],
                }
            ),
            {},
        )


def test_check_source_tool_returns_bounded_json_when_probe_raises(monkeypatch):
    monkeypatch.setattr(
        scout,
        "preview_source",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("secret")),
    )
    payload = json.loads(scout.make_check_source_tool("search.yaml")("https://jobs/acme"))
    assert payload == {
        "ok": False,
        "ats": None,
        "token": None,
        "role_count": None,
        "error": "Source probe failed (RuntimeError).",
        "error_code": "PROBE_ERROR",
    }
