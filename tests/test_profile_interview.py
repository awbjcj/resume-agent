from resume_tailor_harness.profile.interview import (
    InterviewQuestion,
    InterviewRound,
    append_round,
    asked_questions,
    load_history,
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


def test_legacy_history_round_trip_supports_anti_repeat_context(tmp_path):
    assert load_history(tmp_path) == {"rounds": []}
    append_round(tmp_path, "round-1", "run-1", sample_round())

    row = load_history(tmp_path)["rounds"][0]
    assert row["run_id"] == "run-1"
    assert row["answers"] == []
    assert asked_questions(tmp_path) == [
        "What measurable impact did your Acme work have?"
    ]


def test_corpus_tools_are_read_only_capped_and_never_raise(tmp_path):
    from resume_tailor_harness.profile import interview
    from resume_tailor_harness.profile.corpus import add_source

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
