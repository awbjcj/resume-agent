import pytest

from resume_agent.profile.coach import (
    AGENDA_CAP,
    CoachTurn,
    DraftNote,
    NewTopic,
    OpeningTurn,
    TopicUpdate,
    TurnRejected,
    _FORMAT_INSTRUCTIONS,
    _formatter_instructions,
    normalize_opening,
    normalize_recap,
    normalize_turn,
    profile_overview,
    render_agenda,
    render_transcript,
)


def test_opening_formatter_instructions_require_agenda_topics():
    # The opening turn carries its agenda in `topics`; if the formatter is not
    # told to copy that field it emits an empty agenda and every opening turn
    # dies with "opening turn proposed no topics".
    opening = " ".join(_formatter_instructions(OpeningTurn)).lower()
    assert "topics" in opening
    # Ongoing turns have no agenda field, so their instructions stay untouched.
    assert _formatter_instructions(CoachTurn) == _FORMAT_INSTRUCTIONS


def _session(user_texts=("I cut deploy time from 40 min to 6 min.",), n_topics=2):
    return {
        "session_id": "s1",
        "status": "active",
        "turns": [
            {"role": "user", "kind": "", "text": text, "topic_id": "t1", "at": "", "research_actions": []}
            for text in user_texts
        ],
        "topics": [
            {"id": f"t{i}", "gap": f"g{i}", "why_it_matters": "", "related_ref": "", "status": "open", "note_doc_id": None}
            for i in range(1, n_topics + 1)
        ],
        "draft_notes": [],
    }


def test_opening_requires_ask_and_known_topic():
    topics, validated = normalize_opening(
        OpeningTurn(
            message="Welcome!",
            action="ask",
            topic_id="t1",
            topics=[NewTopic(gap=f"gap {index}") for index in range(AGENDA_CAP + 2)],
        )
    )
    assert len(topics) == AGENDA_CAP
    assert validated.coach_turn.topic_id == "t1"
    with pytest.raises(TurnRejected, match="opening action"):
        normalize_opening(
            OpeningTurn(message="bad", action="recap", topic_id="t1", topics=[NewTopic(gap="g")])
        )
    with pytest.raises(TurnRejected, match="unknown topic"):
        normalize_opening(
            OpeningTurn(message="bad", action="ask", topic_id="t9", topics=[NewTopic(gap="g")])
        )


def test_message_action_state_machine_and_single_draft():
    session = _session()
    with pytest.raises(TurnRejected, match="recap"):
        normalize_turn(CoachTurn(message="done", action="recap", topic_id="t1"), session)
    session["topics"][0]["status"] = "drafted"
    session["draft_notes"] = [
        {"topic_id": "t1", "title": "T", "summary": "S", "quotes": ["q"], "status": "pending"}
    ]
    with pytest.raises(TurnRejected, match="open topic"):
        normalize_turn(
            CoachTurn(
                message="again",
                action="draft",
                topic_id="t1",
                draft_note=DraftNote(title="T", summary="S", quotes=["I cut deploy time"]),
            ),
            session,
        )


def test_quote_must_come_from_one_user_turn():
    session = _session(user_texts=("alpha beta", "gamma delta"))
    with pytest.raises(TurnRejected, match="quote"):
        normalize_turn(
            CoachTurn(
                message="draft",
                action="draft",
                topic_id="t1",
                draft_note=DraftNote(title="T", summary="S", quotes=["beta gamma"]),
            ),
            session,
        )
    valid = normalize_turn(
        CoachTurn(
            message="draft",
            action="draft",
            topic_id="t1",
            draft_note=DraftNote(title="T", summary="S", quotes=["alpha   beta"]),
        ),
        session,
    )
    assert valid.draft is not None


def test_add_and_skip_updates_are_bounded_and_consistent():
    validated = normalize_turn(
        CoachTurn(
            message="Noted.",
            action="ask",
            topic_id="t1",
            topic_updates=[TopicUpdate(op="add", gap="CI"), TopicUpdate(op="skip", topic_id="t2")],
        ),
        _session(),
    )
    assert [topic.id for topic in validated.new_topics] == ["t3"]
    assert validated.skipped_topic_ids == ["t2"]


def test_recap_requires_recap_action_and_nonempty_message():
    assert normalize_recap(CoachTurn(message="Covered Acme.", action="recap", topic_id="t1"), _session()) == "Covered Acme."
    with pytest.raises(TurnRejected, match="recap action"):
        normalize_recap(CoachTurn(message="Question?", action="ask", topic_id="t1"), _session())


def test_transcript_is_topic_aware_and_never_exceeds_cap():
    session = _session(user_texts=())
    session["topics"][0]["status"] = "saved"
    session["draft_notes"] = [
        {"topic_id": "t1", "title": "Old", "summary": "Old summary", "quotes": ["old"], "status": "saved"}
    ]
    session["turns"] = [
        {"role": "coach", "kind": "question", "text": "old " + "x" * 500, "topic_id": "t1", "at": "", "research_actions": []},
        {"role": "user", "kind": "", "text": "active " + "y" * 2000, "topic_id": "t2", "at": "", "research_actions": []},
    ]
    rendered = render_transcript(session, char_cap=500)
    assert len(rendered) <= 500
    assert "Old summary" in rendered
    assert "elided" in rendered
    assert "t2 [open]" in render_agenda(session)


def test_profile_overview_degrades_on_fresh_workspace(tmp_path):
    text = profile_overview(tmp_path)
    assert "(no facts yet)" in text
    assert "PREVIOUSLY ASKED" in text


def test_unknown_opening_topic_names_the_valid_ids_so_the_retry_can_recover():
    # Opening topic ids are generated positionally by the validator IN THIS SAME
    # TURN, so the formatter cannot know them ahead of time and will sometimes
    # emit a semantic slug it invented ("deep-agent-impact"). format_with_retry
    # feeds the rejection reason back for exactly one retry, so that reason has
    # to say what a valid id *is* -- otherwise the retry carries no more
    # information than the attempt that just failed and the session dies.
    with pytest.raises(TurnRejected, match="unknown topic") as excinfo:
        normalize_opening(
            OpeningTurn(
                message="hi",
                action="ask",
                topic_id="deep-agent-impact",
                topics=[NewTopic(gap="g1"), NewTopic(gap="g2")],
            )
        )
    message = str(excinfo.value)
    assert "t1" in message and "t2" in message


def test_opening_format_instruction_states_the_positional_id_convention():
    # The formatter is the only thing that fills topic_id, so if the prompt does
    # not name the t1/t2 convention the model has to guess -- and a guess can
    # never match a positionally generated id.
    from resume_agent.profile.coach import _formatter_instructions

    text = " ".join(_formatter_instructions(OpeningTurn))
    assert "t1" in text
