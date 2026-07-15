from concurrent.futures import ThreadPoolExecutor

import pytest

from resume_agent.profile.interview import (
    InterviewQuestion,
    InterviewRound,
    load_history,
)
from resume_agent.services.profile_interview import (
    interview_context,
    interview_history_view,
    run_interview_round,
    submit_interview_answers,
)


class FakeReporter:
    process = "run-1"

    def begin(self, total, label, **extra):
        pass

    def step(self, current, *, label=None, **extra):
        pass

    def checkpoint(self):
        pass


class FakeAgent:
    def __init__(self, content):
        self.content = content

    def run(self, prompt):
        content = self.content

        class Result:
            pass

        Result.content = content
        return Result()


def seed_resume(profile_dir):
    from resume_agent.profile.corpus import add_source

    source = profile_dir.parent / "resume.txt"
    source.write_text("Resume body", encoding="utf-8")
    add_source(profile_dir, source, primary=True)


def raw_round():
    return InterviewRound(
        questions=[
            InterviewQuestion(
                id="duplicate",
                gap="Acme impact",
                question_text="What measurable impact did your Acme work have?",
            ),
            InterviewQuestion(
                id="duplicate",
                gap="Kubernetes evidence",
                question_text="Where did you use Kubernetes and what changed?",
            ),
        ]
    )


def test_context_degrades_gracefully_on_fresh_workspace(tmp_path):
    text = interview_context(tmp_path, session=None)
    assert "(no facts yet)" in text
    assert "(no jobs discovered yet)" in text
    assert "PREVIOUSLY ASKED" in text


def test_worker_normalizes_round_and_appends_actual_run_id(tmp_path):
    result = run_interview_round(
        FakeReporter(),
        profile_dir=tmp_path,
        inspector_agent=FakeAgent("notes"),
        formatter_agent=FakeAgent(raw_round()),
    )

    assert [question["id"] for question in result["questions"]] == ["q1", "q2"]
    assert load_history(tmp_path)["rounds"][0]["run_id"] == "run-1"


def test_submit_requires_primary_and_validates_before_writing(tmp_path):
    result = run_interview_round(
        FakeReporter(),
        profile_dir=tmp_path,
        inspector_agent=FakeAgent("notes"),
        formatter_agent=FakeAgent(raw_round()),
    )
    with pytest.raises(ValueError, match="primary resume"):
        submit_interview_answers(tmp_path, result["roundId"], [("q1", "answer")])
    assert not (tmp_path / "sources.json").exists()


def test_submit_creates_notes_once_and_history_returns_actual_text(tmp_path):
    profile_dir = tmp_path / "profile"
    seed_resume(profile_dir)
    result = run_interview_round(
        FakeReporter(),
        profile_dir=profile_dir,
        inspector_agent=FakeAgent("notes"),
        formatter_agent=FakeAgent(raw_round()),
    )

    doc_ids = submit_interview_answers(
        profile_dir,
        result["roundId"],
        [("q1", "Cut deploy time 40%."), ("q2", "  ")],
    )

    assert len(doc_ids) == 1
    history = interview_history_view(profile_dir)
    assert history["rounds"][0]["answers"] == [
        {
            "questionId": "q1",
            "docId": doc_ids[0],
            "answerText": "Cut deploy time 40%.",
        }
    ]
    with pytest.raises(ValueError, match="already answered"):
        submit_interview_answers(profile_dir, result["roundId"], [("q1", "again")])


def test_concurrent_submissions_only_commit_once(tmp_path):
    profile_dir = tmp_path / "profile"
    seed_resume(profile_dir)
    result = run_interview_round(
        FakeReporter(),
        profile_dir=profile_dir,
        inspector_agent=FakeAgent("notes"),
        formatter_agent=FakeAgent(raw_round()),
    )

    def submit():
        try:
            return submit_interview_answers(
                profile_dir, result["roundId"], [("q1", "Cut latency 30%.")]
            )
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _index: submit(), range(2)))

    assert sum(isinstance(outcome, list) for outcome in outcomes) == 1
    assert (
        sum(
            "already answered" in outcome
            for outcome in outcomes
            if isinstance(outcome, str)
        )
        == 1
    )
