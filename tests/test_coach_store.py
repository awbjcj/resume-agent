from concurrent.futures import ThreadPoolExecutor

import pytest

from resume_agent.profile.coach_store import (
    CoachDraftNote,
    CoachTopic,
    CoachTurnRecord,
    active_session,
    apply_turn_delta,
    create_session,
    end_session,
    list_sessions,
    load_session,
    set_draft_status,
    set_impact,
)
from resume_agent.profile.interview import ResearchAction


def _topic(index: int) -> CoachTopic:
    return CoachTopic(id=f"t{index}", gap=f"gap {index}", why_it_matters="demand")


def _opening() -> CoachTurnRecord:
    return CoachTurnRecord(role="coach", kind="question", text="First?", topic_id="t1")


def _seed(profile_dir, session_id="s1"):
    create_session(profile_dir, session_id, [_topic(1), _topic(2)], _opening())
    return session_id


def test_create_load_and_single_active_session(tmp_path):
    sid = _seed(tmp_path)
    session = load_session(tmp_path, sid)
    assert session["status"] == "active"
    current = active_session(tmp_path)
    assert current is not None
    assert current["session_id"] == sid
    with pytest.raises(ValueError, match="active session exists"):
        create_session(tmp_path, "s2", [_topic(1)], _opening())


def test_unknown_and_unsafe_session_ids_are_rejected(tmp_path):
    assert list_sessions(tmp_path) == []
    with pytest.raises(ValueError, match="unknown session"):
        load_session(tmp_path, "../outside")
    with pytest.raises(ValueError, match="invalid session id"):
        create_session(tmp_path, "../outside", [_topic(1)], _opening())


def test_turn_delta_records_topic_and_research_actions(tmp_path):
    sid = _seed(tmp_path)
    state = apply_turn_delta(
        tmp_path,
        sid,
        user_text="I cut deploy time 40%.",
        coach_turn=CoachTurnRecord(
            role="coach",
            kind="draft_note",
            text="Draft ready.",
            topic_id="t1",
            research_actions=[
                ResearchAction(kind="request_url", target="portfolio", why="More evidence")
            ],
        ),
        new_topics=[CoachTopic(id="t3", gap="CI migration")],
        skipped_topic_ids=["t2"],
        draft=CoachDraftNote(
            topic_id="t1",
            title="Acme deploys",
            summary="Cut deploy time 40%.",
            quotes=["I cut deploy time 40%."],
        ),
    )
    assert state["turns"][-2]["topic_id"] == "t1"
    assert state["turns"][-1]["research_actions"][0]["target"] == "portfolio"
    assert {topic["id"]: topic["status"] for topic in state["topics"]} == {
        "t1": "drafted",
        "t2": "skipped",
        "t3": "open",
    }


def test_end_blocks_turns_but_allows_pending_draft_resolution(tmp_path):
    sid = _seed(tmp_path)
    apply_turn_delta(
        tmp_path,
        sid,
        user_text="evidence",
        coach_turn=CoachTurnRecord(role="coach", kind="draft_note", text="d", topic_id="t1"),
        new_topics=[],
        skipped_topic_ids=[],
        draft=CoachDraftNote(topic_id="t1", title="T", summary="S", quotes=["evidence"]),
    )
    state = end_session(tmp_path, sid, "We covered t1.")
    assert state["status"] == "ended"
    with pytest.raises(ValueError, match="session ended"):
        apply_turn_delta(
            tmp_path,
            sid,
            user_text="more",
            coach_turn=CoachTurnRecord(role="coach", kind="question", text="q", topic_id="t1"),
            new_topics=[],
            skipped_topic_ids=[],
            draft=None,
        )
    state = set_draft_status(tmp_path, sid, "t1", "saved", note_doc_id="doc-1")
    assert state["draft_notes"][0]["status"] == "saved"
    set_impact(tmp_path, sid, {"newFactIds": ["p1"]})
    assert load_session(tmp_path, sid)["impact"] == {"newFactIds": ["p1"]}


def test_concurrent_deltas_do_not_lose_updates(tmp_path):
    sid = _seed(tmp_path)

    def turn(index: int):
        return apply_turn_delta(
            tmp_path,
            sid,
            user_text=f"answer {index}",
            coach_turn=CoachTurnRecord(role="coach", kind="question", text=f"q{index}", topic_id="t1"),
            new_topics=[],
            skipped_topic_ids=[],
            draft=None,
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(turn, range(4)))
    assert len(load_session(tmp_path, sid)["turns"]) == 9
