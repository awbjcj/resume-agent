"""Scripted mock interviews through the service layer with fake runners."""

from types import SimpleNamespace
from typing import Any

import pytest

from resume_agent.db import get_session, init_db, make_engine
from resume_agent.interview.agent import (
    DebriefTurn,
    InterviewTurn,
    NewPlanItem,
    OpeningInterview,
    ReviewItem,
)
from resume_agent.services.mock_interview import (
    load_context,
    run_answer_turn,
    run_debrief_turn,
    run_opening_turn,
    session_view,
    sessions_view,
)
from resume_agent.tracking.tables import Job, ResumeVersion

_ids: tuple[int, int] = (0, 0)


class FakeRunner:
    def __init__(self, outputs: list[Any]) -> None:
        self._outputs = list(outputs)

    def run(self, prompt: str) -> Any:
        return SimpleNamespace(content=self._outputs.pop(0))

    async def arun(self, prompt: str) -> Any:
        return self.run(prompt)


class FakeReporter:
    def begin(self, total, label):
        pass

    def step(self, n=1):
        pass


@pytest.fixture()
def engine(tmp_path):
    engine = make_engine("sqlite://")
    init_db(engine)
    with get_session(engine) as db:
        job = Job(source="manual", company="Acme", title="Engineer", jd_text="Ship Python services")
        db.add(job)
        db.commit()
        db.refresh(job)
        assert job.id is not None
        version = ResumeVersion(job_id=job.id, content_json={"summary": "Builder"})
        db.add(version)
        db.commit()
        db.refresh(version)
        assert version.id is not None
        globals()["_ids"] = (job.id, version.id)
    return engine


def _style():
    return {"stage": "technical", "demeanor": "neutral", "difficulty": "standard", "question_count": 4, "extra": ""}


def _open(tmp_path, engine):
    job_id, version_id = _ids
    opening = OpeningInterview(
        message="Welcome. Walk me through your Python background.",
        plan=[
            NewPlanItem(competency="Python", question_type="role_specific"),
            NewPlanItem(competency="Ownership", question_type="behavioral"),
        ],
    )
    return run_opening_turn(
        FakeReporter(),
        interview_dir=tmp_path,
        engine=engine,
        job_id=job_id,
        resume_version_id=version_id,
        style=_style(),
        interviewer_agent=FakeRunner(["notes"]),
        formatter_agent=FakeRunner([opening]),
    )


def test_opening_creates_session_and_hides_plan(tmp_path, engine):
    view = _open(tmp_path, engine)
    assert view["status"] == "active"
    assert view["company"] == "Acme"
    assert view["plan"] is None  # hidden while active
    assert view["progress"] == {"asked": 1, "total": 2}
    assert view["turns"][0]["role"] == "interviewer"


def test_full_interview_flow(tmp_path, engine):
    sid = _open(tmp_path, engine)["sessionId"]
    run_answer_turn(
        FakeReporter(),
        interview_dir=tmp_path,
        session_id=sid,
        message="I shipped a FastAPI service.",
        interviewer_agent=FakeRunner(["notes"]),
        formatter_agent=FakeRunner(
            [InterviewTurn(message="Tell me about a project you owned end to end.", action="ask", question_id="q2")]
        ),
    )
    run_answer_turn(
        FakeReporter(),
        interview_dir=tmp_path,
        session_id=sid,
        message="I owned the billing migration.",
        interviewer_agent=FakeRunner(["notes"]),
        formatter_agent=FakeRunner([InterviewTurn(message="That's all from me, thank you.", action="conclude")]),
    )
    view = run_debrief_turn(
        FakeReporter(),
        interview_dir=tmp_path,
        session_id=sid,
        interviewer_agent=FakeRunner(["debrief notes"]),
        formatter_agent=FakeRunner(
            [
                DebriefTurn(
                    summary="Good technical depth.",
                    question_reviews=[
                        ReviewItem(question_id="q1", question="Python background", score=4),
                        ReviewItem(question_id="q2", question="Ownership", score=3),
                    ],
                )
            ]
        ),
    )
    assert view["status"] == "ended"
    assert view["plan"] is not None  # revealed after ending
    assert view["debrief"]["summary"] == "Good technical depth."
    summary = sessions_view(tmp_path)["sessions"][0]
    assert summary["overallScore"] == 3.5


def test_debrief_without_answers_ends_deterministically_and_skips_llm(tmp_path, engine):
    # Ending an interview the candidate never answered has nothing to score.
    # Asking the LLM to debrief an empty transcript yields an empty summary that
    # normalize_debrief rejects ("empty debrief summary"), surfacing as a run
    # error. A no-answer session must close deterministically without the LLM.
    sid = _open(tmp_path, engine)["sessionId"]

    class Boom(FakeRunner):
        def __init__(self) -> None:
            super().__init__([])

        def run(self, prompt: str) -> Any:
            raise AssertionError("LLM must not run for a no-answer debrief")

    view = run_debrief_turn(
        FakeReporter(),
        interview_dir=tmp_path,
        session_id=sid,
        interviewer_agent=Boom(),
        formatter_agent=Boom(),
    )
    assert view["status"] == "ended"
    assert view["debrief"]["summary"]
    assert view["debrief"]["questionReviews"] == []


def test_formatter_retry_then_fail(tmp_path, engine):
    sid = _open(tmp_path, engine)["sessionId"]
    bad = InterviewTurn(message="", action="ask", question_id="q2")
    with pytest.raises(Exception):
        run_answer_turn(
            FakeReporter(),
            interview_dir=tmp_path,
            session_id=sid,
            message="answer",
            interviewer_agent=FakeRunner(["notes"]),
            formatter_agent=FakeRunner([bad, bad]),
        )
    # failed run left the session untouched
    assert len(session_view(tmp_path, sid)["turns"]) == 1


def test_opening_prompt_forces_extractable_plan(tmp_path, engine):
    """Regression: the interviewer prompt must demand an explicit plan block.

    The formatter is told to invent nothing, so without an enumerable plan in the
    interviewer's notes it returns ``plan=[]`` and ``normalize_opening`` rejects the
    turn with "opening turn proposed no plan" (the mock-interview-open run then errors
    with no session created).
    """
    job_id, version_id = _ids
    seen: list[str] = []

    class RecordingRunner(FakeRunner):
        def run(self, prompt: str) -> Any:
            seen.append(prompt)
            return super().run(prompt)

    opening = OpeningInterview(
        message="Welcome.",
        plan=[NewPlanItem(competency="Python", question_type="role_specific")],
    )
    run_opening_turn(
        FakeReporter(),
        interview_dir=tmp_path,
        engine=engine,
        job_id=job_id,
        resume_version_id=version_id,
        style=_style(),
        interviewer_agent=RecordingRunner(["notes"]),
        formatter_agent=FakeRunner([opening]),
    )
    interviewer_prompt = seen[0]
    assert "PLAN:" in interviewer_prompt
    assert "competency | question_type" in interviewer_prompt


def test_load_context_guards(engine):
    job_id, version_id = _ids
    with pytest.raises(ValueError, match="unknown job"):
        load_context(engine, 999, version_id)
    with pytest.raises(ValueError, match="unknown resume version"):
        load_context(engine, job_id, 999)
