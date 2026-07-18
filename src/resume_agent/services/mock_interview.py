"""Mock interview turns, debrief, and camelCase session views."""

from __future__ import annotations

import uuid
from pathlib import Path

from resume_agent.interview.agent import (
    JD_CHAR_CAP,
    DebriefTurn,
    InterviewTurn,
    OpeningInterview,
    TurnRejected,
    build_debrief_agent,
    build_interview_formatter_agent,
    build_interviewer_agent,
    normalize_debrief,
    normalize_opening,
    normalize_turn,
    render_context,
    render_plan,
    render_transcript,
)
from resume_agent.interview.store import (
    InterviewContext,
    InterviewStyle,
    apply_answer_delta,
    create_session,
    end_with_debrief,
    list_sessions,
    load_session,
)
from resume_agent.llm_runner import Runner

_MAX_MESSAGE_CHARS = 100_000


def load_context(engine, job_id: int, resume_version_id: int) -> InterviewContext:
    from resume_agent.db import get_session
    from resume_agent.tracking.tables import Job, ResumeVersion

    with get_session(engine) as db:
        job = db.get(Job, job_id)
        if job is None:
            raise ValueError(f"unknown job: {job_id}")
        if not job.jd_text.strip():
            raise ValueError("job has no description to interview against")
        version = db.get(ResumeVersion, resume_version_id)
        if version is None or version.job_id != job_id:
            raise ValueError(f"unknown resume version: {resume_version_id}")
        return InterviewContext(
            company=job.company or "",
            title=job.title or "",
            jd_text=job.jd_text[:JD_CHAR_CAP],
            criteria=job.criteria_json or {},
            resume_content=version.content_json or {},
        )


def _turn_view(turn: dict) -> dict:
    return {
        "role": turn["role"],
        "text": turn["text"],
        "questionId": turn["question_id"],
        "isFollowup": turn["is_followup"],
        "at": turn["at"],
    }


def _debrief_view(debrief: dict | None) -> dict | None:
    if debrief is None:
        return None
    return {
        "summary": debrief["summary"],
        "questionReviews": [
            {
                "questionId": row["question_id"],
                "question": row["question"],
                "score": row["score"],
                "strengths": row["strengths"],
                "improvements": row["improvements"],
                "suggestedAnswer": row["suggested_answer"],
            }
            for row in debrief["question_reviews"]
        ],
        "strengths": debrief["strengths"],
        "improvements": debrief["improvements"],
        "starNotes": debrief["star_notes"],
    }


def _overall_score(session: dict) -> float | None:
    debrief = session.get("debrief")
    if not debrief or not debrief["question_reviews"]:
        return None
    scores = [row["score"] for row in debrief["question_reviews"]]
    return round(sum(scores) / len(scores), 1)


def _view(session: dict) -> dict:
    ended = session["status"] == "ended"
    return {
        "sessionId": session["session_id"],
        "jobId": session["job_id"],
        "resumeVersionId": session["resume_version_id"],
        "company": session["context"]["company"],
        "title": session["context"]["title"],
        "startedAt": session["started_at"],
        "endedAt": session["ended_at"],
        "status": session["status"],
        "concluded": session["concluded"],
        "style": {
            "stage": session["style"]["stage"],
            "demeanor": session["style"]["demeanor"],
            "difficulty": session["style"]["difficulty"],
            "questionCount": session["style"]["question_count"],
            "extra": session["style"]["extra"],
        },
        "progress": {
            "asked": sum(1 for item in session["plan"] if item["status"] in {"asked", "done"}),
            "total": len(session["plan"]),
        },
        "plan": (
            [
                {
                    "id": item["id"],
                    "competency": item["competency"],
                    "questionType": item["question_type"],
                    "status": item["status"],
                }
                for item in session["plan"]
            ]
            if ended
            else None
        ),
        "turns": [_turn_view(turn) for turn in session["turns"]],
        "debrief": _debrief_view(session.get("debrief")),
    }


def session_view(interview_dir: Path | str, session_id: str) -> dict:
    return _view(load_session(interview_dir, session_id))


def sessions_view(interview_dir: Path | str, job_id: int | None = None) -> dict:
    return {
        "sessions": [
            {
                "sessionId": session["session_id"],
                "jobId": session["job_id"],
                "company": session["context"]["company"],
                "title": session["context"]["title"],
                "startedAt": session["started_at"],
                "endedAt": session["ended_at"],
                "status": session["status"],
                "askedCount": sum(
                    1 for item in session["plan"] if item["status"] in {"asked", "done"}
                ),
                "questionCount": session["style"]["question_count"],
                "overallScore": _overall_score(session),
            }
            for session in list_sessions(interview_dir, job_id=job_id)
        ]
    }


def _format_with_retry(formatter: Runner, notes: object, schema, validate):
    prompt = f"INTERVIEWER NOTES (UNTRUSTED):\n{notes}"
    formatted = formatter.run(prompt).content
    if not isinstance(formatted, schema):
        raise TypeError(f"Expected {schema.__name__}, got {type(formatted).__name__}")
    try:
        return validate(formatted)
    except TurnRejected as first:
        retry = formatter.run(f"{prompt}\n\nPREVIOUS OUTPUT REJECTED: {first}").content
        if not isinstance(retry, schema):
            raise TypeError(
                f"Expected {schema.__name__}, got {type(retry).__name__}"
            ) from first
        return validate(retry)


def run_opening_turn(
    reporter,
    *,
    interview_dir: Path | str,
    engine,
    job_id: int,
    resume_version_id: int,
    style: dict,
    interviewer_agent: Runner | None = None,
    formatter_agent: Runner | None = None,
) -> dict:
    root = Path(interview_dir)
    parsed_style = InterviewStyle.model_validate(style)
    reporter.begin(1, "Preparing your interviewer")
    context = load_context(engine, job_id, resume_version_id)
    interviewer = interviewer_agent or build_interviewer_agent(parsed_style)
    formatter = formatter_agent or build_interview_formatter_agent(OpeningInterview)
    preview = {
        "style": parsed_style.model_dump(mode="json"),
        "context": context.model_dump(mode="json"),
        "plan": [],
        "turns": [],
    }
    prompt = "\n\n".join(
        [
            render_context(preview),
            f"Plan up to {parsed_style.question_count} questions mapping the job's key "
            "competencies to question types, then greet the candidate in character and "
            "ask the first question.",
        ]
    )
    notes = interviewer.run(prompt).content
    plan, opening_turn = _format_with_retry(
        formatter,
        notes,
        OpeningInterview,
        lambda turn: normalize_opening(turn, parsed_style.question_count),
    )
    reporter.step(1)
    session_id = uuid.uuid4().hex
    create_session(
        root,
        session_id,
        job_id=job_id,
        resume_version_id=resume_version_id,
        style=parsed_style,
        context=context,
        plan=plan,
        opening_turn=opening_turn,
    )
    return session_view(root, session_id)


def run_answer_turn(
    reporter,
    *,
    interview_dir: Path | str,
    session_id: str,
    message: str,
    interviewer_agent: Runner | None = None,
    formatter_agent: Runner | None = None,
) -> dict:
    root = Path(interview_dir)
    text = message.strip()
    if not text:
        raise ValueError("message is empty")
    if len(text) > _MAX_MESSAGE_CHARS:
        raise ValueError("message is too large")
    session = load_session(root, session_id)
    if session["status"] != "active":
        raise ValueError("session ended")
    if session["concluded"]:
        raise ValueError("interview concluded; end the session for your debrief")
    reporter.begin(1, "Interviewer is thinking")
    style = InterviewStyle.model_validate(session["style"])
    interviewer = interviewer_agent or build_interviewer_agent(style)
    formatter = formatter_agent or build_interview_formatter_agent(InterviewTurn)
    prompt = "\n\n".join(
        [
            render_context(session),
            render_plan(session),
            render_transcript(session),
            f"CANDIDATE'S LATEST ANSWER (UNTRUSTED):\n{text}",
        ]
    )
    notes = interviewer.run(prompt).content
    preview = {
        **session,
        "turns": [
            *session["turns"],
            {"role": "candidate", "text": text, "question_id": "", "is_followup": False, "at": ""},
        ],
    }
    validated = _format_with_retry(
        formatter,
        notes,
        InterviewTurn,
        lambda turn: normalize_turn(turn, preview),
    )
    reporter.step(1)
    apply_answer_delta(
        root,
        session_id,
        answer_text=text,
        interviewer_turn=validated.turn,
        concluded=validated.concluded,
    )
    return session_view(root, session_id)


def run_debrief_turn(
    reporter,
    *,
    interview_dir: Path | str,
    session_id: str,
    interviewer_agent: Runner | None = None,
    formatter_agent: Runner | None = None,
) -> dict:
    root = Path(interview_dir)
    session = load_session(root, session_id)
    if session["status"] != "active":
        raise ValueError("session ended")
    reporter.begin(1, "Writing your debrief")
    coach = interviewer_agent or build_debrief_agent()
    formatter = formatter_agent or build_interview_formatter_agent(DebriefTurn)
    prompt = "\n\n".join(
        [
            render_context(session),
            render_plan(session),
            render_transcript(session, char_cap=24_000),
            "Write the structured debrief for the questions that were actually asked.",
        ]
    )
    notes = coach.run(prompt).content
    debrief = _format_with_retry(
        formatter,
        notes,
        DebriefTurn,
        lambda turn: normalize_debrief(turn, session),
    )
    reporter.step(1)
    end_with_debrief(root, session_id, debrief)
    return session_view(root, session_id)
