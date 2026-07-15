import pytest

from resume_agent.profile.interview import (
    InterviewQuestion,
    InterviewRound,
    ResearchAction,
    append_round,
    asked_questions,
    load_history,
    normalize_round,
    record_answers,
)


def sample_round():
    return InterviewRound(
        questions=[
            InterviewQuestion(
                id="model-id",
                gap="Acme impact",
                question_text="What measurable impact did your Acme work have?",
            )
        ]
    )


def test_history_round_trip_and_empty_submission_is_final(tmp_path):
    assert load_history(tmp_path) == {"rounds": []}
    append_round(tmp_path, "round-1", "run-1", sample_round())
    record_answers(tmp_path, "round-1", [])

    row = load_history(tmp_path)["rounds"][0]
    assert row["run_id"] == "run-1"
    assert row["answers"] == []
    assert row["submitted_at"] is not None
    assert asked_questions(tmp_path) == [
        "What measurable impact did your Acme work have?"
    ]
    with pytest.raises(ValueError, match="already answered"):
        record_answers(tmp_path, "round-1", [])


def test_malformed_history_is_not_silently_discarded(tmp_path):
    (tmp_path / "interview_history.json").write_text("{broken", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid interview history"):
        load_history(tmp_path)


def test_normalize_round_assigns_ids_drops_blanks_and_caps_combined_items():
    raw = InterviewRound(
        questions=[
            InterviewQuestion(id="same", question_text=f"Question {index}?")
            for index in range(7)
        ]
        + [InterviewQuestion(question_text="   ")],
        research_actions=[
            ResearchAction(kind="request_url", target=f"target-{index}", why="why")
            for index in range(4)
        ],
    )

    normalized = normalize_round(raw)

    assert [question.id for question in normalized.questions] == [
        "q1",
        "q2",
        "q3",
        "q4",
        "q5",
        "q6",
        "q7",
    ]
    assert len(normalized.questions) + len(normalized.research_actions) == 8


def test_corpus_tools_are_read_only_capped_and_never_raise(tmp_path):
    from resume_agent.profile import interview
    from resume_agent.profile.corpus import add_source

    source = tmp_path / "resume.md"
    source.write_text("# Resume\n" + "x" * 30_000, encoding="utf-8")
    doc = add_source(tmp_path / "profile", source, primary=True)
    tools = {
        tool.__name__: tool
        for tool in interview.make_corpus_tools(tmp_path / "profile")
    }

    assert doc.id in tools["list_corpus_documents"]()
    assert len(tools["read_document"](doc.id)) <= interview._DOC_READ_CAP + 100
    assert "unknown document" in tools["read_document"]("missing")
    assert isinstance(tools["list_github_sources"](), str)
