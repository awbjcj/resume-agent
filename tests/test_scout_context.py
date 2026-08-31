from resume_tailor_harness.discovery.scout_store import ScoutProposal, SourcePayload
from resume_tailor_harness.services.scout_context import (
    render_goal,
    render_ledger,
    render_transcript,
    session_source_keys,
)


def test_ledger_renders_added_and_dismissed_feedback_as_untrusted():
    session = {
        "proposals": [
            ScoutProposal(
                id="p1",
                kind="source",
                source=SourcePayload(company="Modal", url="https://modal.com/jobs"),
                status="added",
            ).model_dump(mode="json"),
            ScoutProposal(
                id="p2",
                kind="source",
                source=SourcePayload(company="Scale AI", url="https://scale.com/jobs"),
                status="dismissed",
                dismiss_reason="too big",
            ).model_dump(mode="json"),
        ]
    }
    text = render_ledger(session)
    assert "ALREADY ADDED: Modal" in text
    assert "DISMISSED — DO NOT PROPOSE AGAIN:" in text
    assert "Scale AI — user said: too big" in text
    assert "UNTRUSTED USER FEEDBACK" in text


def test_session_keys_dedupe_avoid_without_url_by_company():
    row = ScoutProposal(
        id="p1",
        kind="source",
        source=SourcePayload(company="Acme"),
        check="avoid",
    ).model_dump(mode="json")
    assert "company:acme" in session_source_keys({"proposals": [row]})


def test_goal_and_transcript_keep_untrusted_framing_when_elided():
    session = {
        "goal": "AI infrastructure",
        "turns": [
            {"role": "user", "text": f"message {index} " + "x" * 80, "notice": ""}
            for index in range(20)
        ],
    }
    assert "UNTRUSTED USER GOAL" in render_goal(session)
    rendered = render_transcript(session, char_cap=300)
    assert len(rendered) <= 300
    assert "older turns elided" in rendered
    assert "message 19" in rendered
