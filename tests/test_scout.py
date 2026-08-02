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


def _term_rows(count: int) -> list[dict]:
    return [{"kind": "search_term", "term": {"value": f"term-{index}"}} for index in range(count)]


def test_turn_and_pending_caps_truncate_instead_of_losing_the_turn():
    # The caps are Python-owned policy. A model that overshoots them must cost
    # the user the surplus rows, never the whole turn: a live formatter handed
    # 5 companies answered a rejection retry by expanding past the cap, and the
    # fatal rejection dropped every proposal it had got right.
    validated = normalize_turn(
        ScoutTurnDraft.model_validate({"message": "Too many", "proposals": _term_rows(9)}),
        {"proposals": []},
    )
    assert len(validated.proposals) == scout.PROPOSAL_CAP
    assert validated.notice == scout.PROPOSALS_TRUNCATED_NOTICE

    room_for_two = normalize_turn(
        ScoutTurnDraft.model_validate({"message": "Some more", "proposals": _term_rows(5)}),
        {"proposals": [{"status": "pending"}] * (scout.PENDING_CAP - 2)},
    )
    assert len(room_for_two.proposals) == 2

    full = normalize_turn(
        ScoutTurnDraft.model_validate({"message": "One more", "proposals": _term_rows(1)}),
        {"proposals": [{"status": "pending"}] * scout.PENDING_CAP},
    )
    assert full.proposals == []


def test_turn_kind_is_python_owned_not_model_supplied():
    # The caller already knows whether it asked for a reply or a recap, so a
    # discriminator the model has to guess buys nothing and costs everything:
    # gpt-5.6-luna answered a live turn with kind="scout_turn" and the whole
    # turn -- five correctly formatted proposals -- was thrown away.
    turn = ScoutTurnDraft.model_validate(
        {
            "kind": "scout_turn",
            "message": "I found four leads.",
            "proposals": [
                {"kind": "source", "source": {"company": "Acme", "url": "https://acme.test/jobs"}}
            ],
        }
    )
    validated = normalize_turn(turn, {"proposals": []})
    assert validated.notice == ""
    assert len(validated.proposals) == 1


def test_recap_ignores_model_supplied_deltas():
    recap = normalize_recap(
        ScoutTurnDraft.model_validate(
            {
                "kind": "wrap_up",
                "message": "Done",
                "goal_update": "changed",
                "proposals": [{"kind": "search_term", "term": {"value": "python"}}],
            }
        ),
        {},
    )
    assert recap == "Done"
    with pytest.raises(TurnRejected, match="message"):
        normalize_recap(ScoutTurnDraft.model_validate({"message": "  "}), {})


@pytest.mark.parametrize(
    "proposal",
    [
        {"kind": "careers_source", "source": {"company": "Acme", "url": "https://acme.test"}},
        {"kind": "source", "source": {"company": "Acme", "url": "https://acme.test"}, "disposition": "include"},
    ],
)
def test_invented_vocabulary_degrades_per_proposal(proposal):
    # An out-of-vocabulary label is one bad row, not a broken turn, so the
    # non-strict retry pass has to be able to drop it and keep the reply.
    turn = ScoutTurnDraft.model_validate({"message": "Found it", "proposals": [proposal]})
    with pytest.raises(ProposalRejected):
        normalize_turn(turn, {"proposals": []}, strict=True)
    degraded = normalize_turn(turn, {"proposals": []}, strict=False)
    assert degraded.message == "Found it"
    assert degraded.notice == scout.PROPOSALS_OMITTED_NOTICE


def test_draft_schema_publishes_its_closed_vocabularies():
    # The provider's grammar is the only layer that can stop an invented label
    # before it costs a round trip, and it only can when the schema carries the
    # enum. Coach and interview drafts already do this with Literal fields.
    schema = ScoutTurnDraft.model_json_schema()
    definitions = schema.get("$defs", {})
    assert definitions["ScoutProposalDraft"]["properties"]["kind"]["enum"] == [
        "source",
        "search_term",
    ]
    assert definitions["ScoutProposalDraft"]["properties"]["disposition"]["enum"] == [
        "propose",
        "avoid",
    ]
    assert set(definitions["TermDraft"]["properties"]["term_kind"]["enum"]) == set(
        scout.SUGGESTION_KINDS
    )
    assert "kind" not in schema["properties"]


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
