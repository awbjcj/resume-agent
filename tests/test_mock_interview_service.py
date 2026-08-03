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
from resume_agent.sessions.stream import Completed, Notice, TextDelta, ToolStarted
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

    def checkpoint(self):
        pass


class RecordingSink:
    def __init__(self):
        self.events = []

    def emit(self, event):
        self.events.append(event)

    def close(self):
        pass

    @property
    def text(self):
        return "".join(
            event.text for event in self.events if isinstance(event, TextDelta)
        )


class StreamingRunner(FakeRunner):
    def __init__(self, prose: str):
        self.full = f"{prose}\n---METADATA---\naction: ask\nquestion: q2"
        self.prompts: list[str] = []

    def stream(self, prompt):
        self.prompts.append(prompt)
        yield TextDelta(self.full[:8])
        yield ToolStarted("call-1", "read_jd", "")
        yield TextDelta(self.full[8:])
        yield Completed(SimpleNamespace(content=self.full))

    def run(self, prompt):
        return SimpleNamespace(content=self.full)


class PromptFollowingOpeningRunner(FakeRunner):
    """Small deterministic model double that follows the requested wire format."""

    def stream(self, prompt):
        if "---METADATA---" in prompt:
            full = (
                "Welcome. Tell me about your Python background.\n"
                "---METADATA---\n"
                "action: ask\n"
                "question_id: q1\n"
                "follow_up: false\n"
                "plan:\n"
                "1. Python | role_specific\n"
                "2. Ownership | behavioral"
            )
        else:
            full = (
                "PLAN:\n"
                "1. Python | role_specific\n"
                "2. Ownership | behavioral\n\n"
                "OPENING:\n"
                "Welcome. Tell me about your Python background."
            )
        yield TextDelta(full)
        yield Completed(SimpleNamespace(content=full))


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


def test_opening_instruction_keeps_plan_out_of_candidate_chat(tmp_path, engine):
    job_id, version_id = _ids
    sink = RecordingSink()
    opening = OpeningInterview(
        message="ignored",
        plan=[
            NewPlanItem(competency="Python", question_type="role_specific"),
            NewPlanItem(competency="Ownership", question_type="behavioral"),
        ],
    )

    view = run_opening_turn(
        FakeReporter(),
        interview_dir=tmp_path,
        engine=engine,
        job_id=job_id,
        resume_version_id=version_id,
        style=_style(),
        interviewer_agent=PromptFollowingOpeningRunner([]),
        formatter_agent=FakeRunner([opening]),
        sink=sink,
    )

    expected = "Welcome. Tell me about your Python background."
    assert sink.text == expected
    assert view["turns"][0]["text"] == expected
    assert view["plan"] is None


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


def test_answer_streams_and_stores_interviewer_prose(tmp_path, engine):
    sid = _open(tmp_path, engine)["sessionId"]
    sink = RecordingSink()
    interviewer = StreamingRunner("Tell me about ownership.")

    run_answer_turn(
        FakeReporter(),
        interview_dir=tmp_path,
        session_id=sid,
        message="I shipped a FastAPI service.",
        interviewer_agent=interviewer,
        formatter_agent=FakeRunner(
            [InterviewTurn(message="ignored", action="ask", question_id="q2")]
        ),
        sink=sink,
    )

    assert sink.text == "Tell me about ownership."
    assert session_view(tmp_path, sid)["turns"][-1]["text"] == sink.text
    assert any(isinstance(event, ToolStarted) for event in sink.events)
    assert interviewer.prompts[0].index("TRANSCRIPT:") < interviewer.prompts[0].index(
        "QUESTION PLAN"
    )


def test_streamed_question_survives_structural_formatter_failure(tmp_path, engine):
    sid = _open(tmp_path, engine)["sessionId"]
    bad = InterviewTurn(message="", action="ask", question_id="missing")
    sink = RecordingSink()

    view = run_answer_turn(
        FakeReporter(),
        interview_dir=tmp_path,
        session_id=sid,
        message="I shipped a FastAPI service.",
        interviewer_agent=StreamingRunner("Tell me about ownership."),
        formatter_agent=FakeRunner([bad, bad]),
        sink=sink,
    )

    assert view["turns"][-1]["text"] == "Tell me about ownership."
    assert "plan was unchanged" in view["turns"][-1]["notice"]
    assert any(isinstance(event, Notice) for event in sink.events)


def test_streamed_question_survives_unparsable_formatter_output(
    tmp_path, engine, caplog
):
    sid = _open(tmp_path, engine)["sessionId"]

    view = run_answer_turn(
        FakeReporter(),
        interview_dir=tmp_path,
        session_id=sid,
        message="I shipped a FastAPI service.",
        interviewer_agent=StreamingRunner("Tell me about ownership."),
        formatter_agent=FakeRunner(["not structured output"]),
    )

    assert view["turns"][-1]["text"] == "Tell me about ownership."
    assert "plan was unchanged" in view["turns"][-1]["notice"]
    assert "Interview formatter returned unusable output" in caplog.text


def test_blocking_formatter_question_survives_structural_failure(tmp_path, engine):
    sid = _open(tmp_path, engine)["sessionId"]
    bad = InterviewTurn(
        message="Tell me about ownership.", action="ask", question_id="missing"
    )

    view = run_answer_turn(
        FakeReporter(),
        interview_dir=tmp_path,
        session_id=sid,
        message="I shipped a FastAPI service.",
        interviewer_agent=FakeRunner(["notes"]),
        formatter_agent=FakeRunner([bad, bad]),
    )

    assert view["turns"][-1]["text"] == "Tell me about ownership."
    assert view["turns"][-1]["notice"]


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


def test_debrief_with_empty_candidate_record_still_skips_llm(tmp_path, engine):
    sid = _open(tmp_path, engine)["sessionId"]

    from resume_agent.interview.store import mutate_session

    mutate_session(
        tmp_path,
        sid,
        lambda session: session["turns"].append(
            {
                "role": "candidate",
                "text": "   ",
                "question_id": "q1",
                "is_followup": False,
                "at": "",
            }
        ),
    )

    class Boom(FakeRunner):
        def __init__(self) -> None:
            super().__init__([])

        def run(self, prompt: str) -> Any:
            raise AssertionError("LLM must not run for an empty-answer debrief")

    view = run_debrief_turn(
        FakeReporter(),
        interview_dir=tmp_path,
        session_id=sid,
        interviewer_agent=Boom(),
        formatter_agent=Boom(),
    )
    assert view["status"] == "ended"
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
    assert "---METADATA---" in interviewer_prompt
    assert "plan:" in interviewer_prompt
    assert "competency | question_type" in interviewer_prompt


def test_load_context_guards(engine):
    job_id, version_id = _ids
    with pytest.raises(ValueError, match="unknown job"):
        load_context(engine, 999, version_id)
    with pytest.raises(ValueError, match="unknown resume version"):
        load_context(engine, job_id, 999)
