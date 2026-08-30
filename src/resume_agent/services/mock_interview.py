"""Mock interview turns, debrief, and camelCase session views."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from pathlib import Path

from resume_agent import llm_runner
from resume_agent.career_skills.models import AgentFamily, SkillUse
from resume_agent.career_skills.provenance import append_skill_use
from resume_agent.career_skills.registry import CareerSkillRegistry
from resume_agent.config import get_settings
from resume_agent.interview.agent import (
    JD_CHAR_CAP,
    DebriefTurn,
    InterviewTurn,
    OpeningInterview,
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
    InterviewDebrief,
    InterviewStyle,
    apply_answer_delta,
    attach_turn_audio,
    create_session,
    end_with_debrief,
    list_sessions,
    load_session,
    mark_turn_audio_failed,
)
from resume_agent.llm_runner import Runner, UnparsedAgentOutput, expect_text
from resume_agent.sessions.stream import Notice, NullSink, StreamSink
from resume_agent.sessions.turns import TurnRejected, format_with_retry, persona_output

_MAX_MESSAGE_CHARS = 100_000
_EMPTY_DEBRIEF_SUMMARY = (
    "You ended this interview before answering any questions, so there was nothing "
    "to score. Start a new session whenever you're ready to practice."
)
_DEGRADED_HINTS = [
    "Use one specific example and make your individual contribution clear.",
    "Structure the response around context, actions, and a measurable result.",
]

logger = logging.getLogger(__name__)


def _interview_skill(name: str, use: str):
    registry = CareerSkillRegistry.from_settings(get_settings())
    return registry.require(name, family=AgentFamily.INTERVIEW, use=use)


def _build_interviewer(style, skill):
    try:
        return build_interviewer_agent(style, skill=skill)
    except TypeError as exc:
        if "unexpected keyword argument 'skill'" not in str(exc):
            raise
        return build_interviewer_agent(style)


def _build_debrief(skill):
    try:
        return build_debrief_agent(skill=skill)
    except TypeError as exc:
        if "unexpected keyword argument 'skill'" not in str(exc):
            raise
        return build_debrief_agent()


# The interviewer writes free-form notes that a cheap formatter then projects into
# the OpeningInterview schema. The formatter is told to invent nothing, so the plan
# only survives if these notes spell it out explicitly — otherwise normalize_opening
# rejects the turn with "opening turn proposed no plan". Keep that block below the
# persona boundary so it can never become candidate-facing chat.
_OPENING_INSTRUCTION = (
    "First design an interview PLAN of up to {count} questions mapping the job's key "
    "competencies to question types (behavioral, role_specific, system_design, and the "
    "like). Greet the candidate in character and ask only the first question before "
    "revealing any plan details. Then write the metadata boundary and the complete plan "
    "as an explicit numbered list, one item per line, formatted as "
    "`competency | question_type`. Format your response exactly as:\n"
    "<your in-character greeting and first question>\n"
    "---METADATA---\n"
    "action: ask\nquestion_id: q1\nfollow_up: false\n"
    "hints:\n- <concise suggestion>\n- <concise suggestion>\n"
    "plan:\n1. <competency> | <question_type>\n2. ..."
)


def load_context(engine, job_id: int, resume_version_id: int) -> InterviewContext:
    from resume_agent.db import get_session
    from resume_agent.services.company_intelligence import load_company_intelligence
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
        company_intelligence = load_company_intelligence(db, job.company)
        return InterviewContext(
            company=job.company or "",
            title=job.title or "",
            jd_text=job.jd_text[:JD_CHAR_CAP],
            criteria=job.criteria_json or {},
            resume_content=version.content_json or {},
            company_intelligence=(
                company_intelligence.model_dump(mode="json")
                if company_intelligence is not None
                else {}
            ),
        )


SpeechSynthesizer = Callable[[str], bytes]


def _turn_view(turn: dict, *, session_id: str, turn_index: int) -> dict:
    ready = turn.get("audio_status") == "ready" and bool(turn.get("audio_ref"))
    return {
        "role": turn["role"],
        "text": turn["text"],
        "questionId": turn["question_id"],
        "isFollowup": turn["is_followup"],
        "at": turn["at"],
        "notice": turn.get("notice", ""),
        "hints": turn.get("hints", []),
        "audioStatus": turn.get("audio_status", "none"),
        "audioUrl": (
            f"/api/interview/sessions/{session_id}/turns/{turn_index}/audio"
            if ready
            else None
        ),
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


def _has_candidate_answer(session: dict) -> bool:
    """Return whether the transcript contains a substantive candidate answer.

    A partially written or legacy candidate record must not make the debrief
    path call the formatter. The formatter has no useful scorecard to produce
    in that state, and its guessed question ids can turn an otherwise harmless
    early exit into a ``TurnRejected`` run error.
    """

    return any(
        turn["role"] == "candidate" and bool(turn.get("text", "").strip())
        for turn in session["turns"]
    )


def _view(session: dict) -> dict:
    ended = session["status"] == "ended"
    return {
        "sessionId": session["session_id"],
        "sessionTitle": session["session_title"],
        "jobId": session["job_id"],
        "resumeVersionId": session["resume_version_id"],
        "company": session["context"]["company"],
        "title": session["context"]["title"],
        "startedAt": session["started_at"],
        "endedAt": session["ended_at"],
        "status": session["status"],
        "archivedAt": session["archived_at"],
        "concluded": session["concluded"],
        "style": {
            "stage": session["style"]["stage"],
            "demeanor": session["style"]["demeanor"],
            "difficulty": session["style"]["difficulty"],
            "questionCount": session["style"]["question_count"],
            "extra": session["style"]["extra"],
            "responseMode": session["style"].get("response_mode", "text"),
        },
        "progress": {
            "asked": sum(
                1 for item in session["plan"] if item["status"] in {"asked", "done"}
            ),
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
        "turns": [
            _turn_view(turn, session_id=session["session_id"], turn_index=index)
            for index, turn in enumerate(session["turns"])
        ],
        "debrief": _debrief_view(session.get("debrief")),
    }


def session_view(interview_dir: Path | str, session_id: str) -> dict:
    return _view(load_session(interview_dir, session_id))


def sessions_view(
    interview_dir: Path | str,
    job_id: int | None = None,
    *,
    include_archived: bool = False,
    status: str | None = None,
) -> dict:
    rows = list_sessions(
        interview_dir, job_id=job_id, include_archived=include_archived
    )
    if status is not None:
        rows = [row for row in rows if row["status"] == status]
    return {
        "sessions": [
            {
                "sessionId": session["session_id"],
                "sessionTitle": session["session_title"],
                "jobId": session["job_id"],
                "company": session["context"]["company"],
                "title": session["context"]["title"],
                "startedAt": session["started_at"],
                "endedAt": session["ended_at"],
                "status": session["status"],
                "archivedAt": session["archived_at"],
                "askedCount": sum(
                    1 for item in session["plan"] if item["status"] in {"asked", "done"}
                ),
                "questionCount": session["style"]["question_count"],
                "overallScore": _overall_score(session),
            }
            for session in rows
        ]
    }


def _synthesize_turn(
    interview_dir: Path | str,
    session_id: str,
    turn_index: int,
    text: str,
    synthesizer: SpeechSynthesizer | None,
) -> None:
    try:
        audio = (synthesizer or llm_runner.synthesize_speech)(text)
        attach_turn_audio(interview_dir, session_id, turn_index, audio)
    except Exception:
        logger.warning(
            "Interview speech synthesis failed for session %s turn %s",
            session_id,
            turn_index,
            exc_info=True,
        )
        mark_turn_audio_failed(interview_dir, session_id, turn_index)


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
    sink: StreamSink | None = None,
    speech_synthesizer: SpeechSynthesizer | None = None,
) -> dict:
    root = Path(interview_dir)
    parsed_style = InterviewStyle.model_validate(style)
    reporter.begin(1, "Preparing your interviewer")
    context = load_context(engine, job_id, resume_version_id)
    interviewer = interviewer_agent or _build_interviewer(
        parsed_style,
        _interview_skill("interview-prep-generator", "interview_prep"),
    )
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
            _OPENING_INSTRUCTION.format(count=parsed_style.question_count),
        ]
    )
    output_sink = sink or NullSink()
    prose, notes = persona_output(
        interviewer, prompt, output_sink, reporter, source="interviewer notes"
    )
    plan, opening_turn = format_with_retry(
        formatter,
        notes,
        OpeningInterview,
        lambda turn, strict: normalize_opening(
            turn, parsed_style.question_count, strict
        ),
        label="INTERVIEWER NOTES",
    )
    if prose:
        opening_turn = opening_turn.model_copy(update={"text": prose})
    skill_uses = []
    if getattr(interviewer, "run_meta", None) is not None:
        skill_uses = [
            SkillUse.model_validate(use)
            for use in append_skill_use(None, interviewer, "opening")
        ]
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
        skill_uses=skill_uses,
    )
    if parsed_style.response_mode == "audio_preferred":
        _synthesize_turn(root, session_id, 0, opening_turn.text, speech_synthesizer)
    return session_view(root, session_id)


def run_answer_turn(
    reporter,
    *,
    interview_dir: Path | str,
    session_id: str,
    message: str,
    interviewer_agent: Runner | None = None,
    formatter_agent: Runner | None = None,
    sink: StreamSink | None = None,
    speech_synthesizer: SpeechSynthesizer | None = None,
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
    interviewer = interviewer_agent or _build_interviewer(
        style,
        _interview_skill("mock-interview-coach", "interview_turn"),
    )
    formatter = formatter_agent or build_interview_formatter_agent(InterviewTurn)
    prompt = "\n\n".join(
        [
            render_context(session),
            render_transcript(session),
            render_plan(session),
            f"CANDIDATE'S LATEST ANSWER (UNTRUSTED):\n{text}",
        ]
    )
    output_sink = sink or NullSink()
    prose, notes = persona_output(
        interviewer, prompt, output_sink, reporter, source="interviewer notes"
    )
    preview = {
        **session,
        "turns": [
            *session["turns"],
            {
                "role": "candidate",
                "text": text,
                "question_id": "",
                "is_followup": False,
                "at": "",
            },
        ],
    }
    try:
        validated = format_with_retry(
            formatter,
            notes,
            InterviewTurn,
            lambda turn, strict: normalize_turn(turn, preview, strict=strict),
            label="INTERVIEWER NOTES",
        )
    except (TurnRejected, UnparsedAgentOutput) as exc:
        fallback_text = prose or getattr(exc, "fallback_text", "")
        if not fallback_text:
            raise
        if isinstance(exc, UnparsedAgentOutput):
            logger.warning("Interview formatter returned unusable output: %s", exc)
        validated = _degraded_turn(session, fallback_text)
    if prose:
        validated.turn = validated.turn.model_copy(update={"text": prose})
    skill_uses = []
    if getattr(interviewer, "run_meta", None) is not None:
        skill_uses = [
            SkillUse.model_validate(use)
            for use in append_skill_use(None, interviewer, "turn")
        ]
    reporter.step(1)
    updated = apply_answer_delta(
        root,
        session_id,
        answer_text=text,
        interviewer_turn=validated.turn,
        concluded=validated.concluded,
        skill_uses=skill_uses,
    )
    if style.response_mode == "audio_preferred":
        _synthesize_turn(
            root,
            session_id,
            len(updated["turns"]) - 1,
            validated.turn.text,
            speech_synthesizer,
        )
    if validated.notice:
        output_sink.emit(Notice(validated.notice))
    return session_view(root, session_id)


def _degraded_turn(session: dict, prose: str):
    from resume_agent.interview.agent import ValidatedInterviewTurn
    from resume_agent.interview.store import InterviewTurnRecord

    question_id = next(
        (item["id"] for item in session["plan"] if item["status"] == "asked"),
        "",
    )
    notice = "Some turn details could not be read, so the interview plan was unchanged."
    return ValidatedInterviewTurn(
        turn=InterviewTurnRecord(
            role="interviewer",
            text=prose,
            question_id=question_id,
            is_followup=True,
            notice=notice,
            hints=_DEGRADED_HINTS,
        ),
        notice=notice,
    )


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
    # An interview the candidate never answered has nothing to score; asking the
    # LLM to debrief an empty transcript yields an empty summary that
    # normalize_debrief rejects ("empty debrief summary"). Close it deterministically.
    if not _has_candidate_answer(session):
        reporter.begin(1, "Closing your interview")
        end_with_debrief(
            root, session_id, InterviewDebrief(summary=_EMPTY_DEBRIEF_SUMMARY)
        )
        reporter.step(1)
        return session_view(root, session_id)
    reporter.begin(1, "Writing your debrief")
    coach = interviewer_agent or _build_debrief(
        _interview_skill("mock-interview-coach", "debrief")
    )
    formatter = formatter_agent or build_interview_formatter_agent(DebriefTurn)
    prompt = "\n\n".join(
        [
            render_context(session),
            render_plan(session),
            render_transcript(session, char_cap=24_000),
            "Write the structured debrief for the questions that were actually asked.",
        ]
    )
    notes = expect_text(coach.run(prompt), source="debrief notes")
    debrief = format_with_retry(
        formatter,
        notes,
        DebriefTurn,
        lambda turn, strict: normalize_debrief(turn, session, strict),
        label="INTERVIEWER NOTES",
    )
    reporter.step(1)
    skill_uses = []
    if getattr(coach, "run_meta", None) is not None:
        skill_uses = [
            SkillUse.model_validate(use)
            for use in append_skill_use(None, coach, "debrief")
        ]
    end_with_debrief(root, session_id, debrief, skill_uses=skill_uses)
    return session_view(root, session_id)
