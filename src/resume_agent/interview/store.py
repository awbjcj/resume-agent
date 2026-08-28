"""Durable Mock Interview sessions with delta-under-lock mutations."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
import re
from typing import Literal
import uuid

from pydantic import Field

from resume_agent.models.base import ExtensibleModel
from resume_agent.career_skills.models import SkillUse
from resume_agent.sessions.store import SessionModel, SessionStore, now_iso, valid_session_id
from resume_agent.security.paths import confined_path

STYLE_EXTRA_CAP = 2_000
_AUDIO_REF = re.compile(r"[a-f0-9]{32}\Z")


class InterviewStyle(ExtensibleModel):
    stage: Literal[
        "recruiter_screen", "hiring_manager", "technical", "behavioral"
    ] = "hiring_manager"
    demeanor: Literal["warm", "neutral", "stress"] = "neutral"
    difficulty: Literal["easy", "standard", "hard"] = "standard"
    question_count: int = Field(default=8, ge=4, le=12)
    extra: str = Field(default="", max_length=STYLE_EXTRA_CAP)
    response_mode: Literal["text", "audio_preferred"] = "text"


class InterviewContext(ExtensibleModel):
    """JD + resume snapshot frozen at opening; a later job edit never re-bases a transcript."""

    company: str = ""
    title: str = ""
    jd_text: str = ""
    criteria: dict = Field(default_factory=dict)
    resume_content: dict = Field(default_factory=dict)


class PlanItem(ExtensibleModel):
    id: str = ""
    competency: str = ""
    question_type: str = ""
    status: Literal["pending", "asked", "done"] = "pending"


class InterviewTurnRecord(ExtensibleModel):
    role: Literal["interviewer", "candidate"] = "candidate"
    text: str = ""
    question_id: str = ""
    is_followup: bool = False
    at: str = ""
    notice: str = ""
    audio_status: Literal["none", "ready", "failed"] = "none"
    audio_ref: str = ""


class QuestionReview(ExtensibleModel):
    question_id: str = ""
    question: str = ""
    score: int = 0
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    suggested_answer: str = ""


class InterviewDebrief(ExtensibleModel):
    summary: str = ""
    question_reviews: list[QuestionReview] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    improvements: list[str] = Field(default_factory=list)
    star_notes: str = ""


class InterviewSession(SessionModel):
    job_id: int = 0
    resume_version_id: int = 0
    ended_at: str | None = None
    concluded: bool = False
    style: InterviewStyle = Field(default_factory=InterviewStyle)
    context: InterviewContext = Field(default_factory=InterviewContext)
    plan: list[PlanItem] = Field(default_factory=list)
    turns: list[InterviewTurnRecord] = Field(default_factory=list)
    debrief: InterviewDebrief | None = None
    skill_uses: list[SkillUse] = Field(default_factory=list)


_STORE: SessionStore[InterviewSession] = SessionStore(InterviewSession, label="interview")


def _valid_session_id(session_id: str) -> bool:
    return valid_session_id(session_id)


def interview_lock() -> AbstractContextManager[None]:
    """Serialize interview session mutations in this process."""
    return _STORE.lock()


def _now() -> str:
    return now_iso()


def _write(interview_dir: Path | str, session: dict) -> None:
    _STORE.write(interview_dir, session)


def list_sessions(
    interview_dir: Path | str,
    job_id: int | None = None,
    *,
    include_archived: bool = False,
) -> list[dict]:
    sessions = _STORE.list(interview_dir, include_archived=include_archived)
    if job_id is not None:
        sessions = [row for row in sessions if row["job_id"] == job_id]
    return sessions


def load_session(interview_dir: Path | str, session_id: str) -> dict:
    return _STORE.load(interview_dir, session_id)


def active_sessions(interview_dir: Path | str) -> list[dict]:
    return _STORE.active(interview_dir)


def active_session_for_job(interview_dir: Path | str, job_id: int) -> dict | None:
    return next(
        (row for row in active_sessions(interview_dir) if row["job_id"] == job_id),
        None,
    )


def active_session(interview_dir: Path | str) -> dict | None:
    """Compatibility projection for callers that only need any active session."""
    return next(iter(active_sessions(interview_dir)), None)


def create_session(
    interview_dir: Path | str,
    session_id: str,
    *,
    job_id: int,
    resume_version_id: int,
    style: InterviewStyle,
    context: InterviewContext,
    plan: list[PlanItem],
    opening_turn: InterviewTurnRecord,
    skill_uses: list[SkillUse] | None = None,
) -> None:
    if not _valid_session_id(session_id):
        raise ValueError("invalid session id")
    plan_ids = [item.id for item in plan]
    if not plan or len(plan_ids) != len(set(plan_ids)):
        raise ValueError("invalid interview plan")
    if opening_turn.question_id not in set(plan_ids):
        raise ValueError("opening turn references unknown question")
    with interview_lock():
        if active_session_for_job(interview_dir, job_id) is not None:
            raise ValueError(f"active session exists for job {job_id}")
        now = _now()
        opened = [
            item.model_copy(
                update={"status": "asked" if item.id == opening_turn.question_id else item.status}
            )
            for item in plan
        ]
        _write(
            interview_dir,
            InterviewSession(
                session_id=session_id,
                job_id=job_id,
                resume_version_id=resume_version_id,
                started_at=now,
                style=style,
                context=context,
                plan=opened,
                turns=[opening_turn.model_copy(update={"at": now})],
                skill_uses=skill_uses or [],
            ).model_dump(mode="json"),
        )


def mutate_session(
    interview_dir: Path | str,
    session_id: str,
    fn: Callable[[dict], None],
) -> dict:
    return _STORE.mutate(interview_dir, session_id, fn)


def _audio_path(interview_dir: Path | str, audio_ref: str) -> Path:
    if not _AUDIO_REF.fullmatch(audio_ref):
        raise ValueError("audio unavailable")
    audio_root = confined_path(interview_dir, "audio")
    return confined_path(audio_root, f"{audio_ref}.mp3")


def attach_turn_audio(
    interview_dir: Path | str,
    session_id: str,
    turn_index: int,
    audio: bytes,
) -> Path:
    """Atomically attach synthesized MP3 bytes to one interviewer turn."""

    if not audio:
        raise ValueError("audio is empty")
    root = Path(interview_dir)
    with interview_lock():
        session = load_session(root, session_id)
        if turn_index < 0 or turn_index >= len(session["turns"]):
            raise ValueError("unknown interview turn")
        turn = session["turns"][turn_index]
        if turn["role"] != "interviewer":
            raise ValueError("audio is only available for interviewer turns")

        audio_ref = uuid.uuid4().hex
        target = _audio_path(root, audio_ref)
        target.parent.mkdir(parents=True, exist_ok=True)
        staged = confined_path(target.parent, f".{audio_ref}-{uuid.uuid4().hex}.tmp")
        old_ref = turn.get("audio_ref", "")
        try:
            staged.write_bytes(audio)
            staged.replace(target)
            turn["audio_ref"] = audio_ref
            turn["audio_status"] = "ready"
            _write(root, session)
        except BaseException:
            staged.unlink(missing_ok=True)
            target.unlink(missing_ok=True)
            raise
        if old_ref:
            _audio_path(root, old_ref).unlink(missing_ok=True)
        return target


def mark_turn_audio_failed(
    interview_dir: Path | str, session_id: str, turn_index: int
) -> None:
    """Record a non-fatal synthesis failure so clients reveal the transcript."""

    def apply(session: dict) -> None:
        if turn_index < 0 or turn_index >= len(session["turns"]):
            raise ValueError("unknown interview turn")
        turn = session["turns"][turn_index]
        if turn["role"] != "interviewer":
            raise ValueError("audio is only available for interviewer turns")
        turn["audio_status"] = "failed"
        turn["audio_ref"] = ""

    mutate_session(interview_dir, session_id, apply)


def turn_audio_path(
    interview_dir: Path | str, session_id: str, turn_index: int
) -> Path:
    """Resolve a ready audio artifact after validating session and turn custody."""

    session = load_session(interview_dir, session_id)
    if turn_index < 0 or turn_index >= len(session["turns"]):
        raise ValueError("unknown interview turn")
    turn = session["turns"][turn_index]
    if turn.get("audio_status") != "ready" or not turn.get("audio_ref"):
        raise ValueError("audio unavailable")
    path = _audio_path(interview_dir, turn["audio_ref"])
    if not path.is_file():
        raise ValueError("audio unavailable")
    return path


def _delete_audio_artifacts(interview_dir: Path | str, session: dict) -> None:
    for turn in session.get("turns", []):
        audio_ref = turn.get("audio_ref", "")
        if audio_ref:
            _audio_path(interview_dir, audio_ref).unlink(missing_ok=True)


def apply_answer_delta(
    interview_dir: Path | str,
    session_id: str,
    *,
    answer_text: str,
    interviewer_turn: InterviewTurnRecord,
    concluded: bool,
    skill_uses: list[SkillUse] | None = None,
) -> dict:
    def apply(session: dict) -> None:
        if session["status"] != "active":
            raise ValueError("session ended")
        if session["concluded"]:
            raise ValueError("interview concluded")
        now = _now()
        current = next(
            (item["id"] for item in session["plan"] if item["status"] == "asked"), ""
        )
        session["turns"].append(
            InterviewTurnRecord(
                role="candidate", text=answer_text, question_id=current, at=now
            ).model_dump(mode="json")
        )
        if skill_uses:
            session["skill_uses"].extend(
                SkillUse.model_validate(use).model_dump(mode="json") for use in skill_uses
            )
        session["turns"].append(
            interviewer_turn.model_copy(update={"at": now}).model_dump(mode="json")
        )
        if concluded:
            session["concluded"] = True
            for item in session["plan"]:
                if item["status"] == "asked":
                    item["status"] = "done"
        elif not interviewer_turn.is_followup:
            for item in session["plan"]:
                if item["status"] == "asked":
                    item["status"] = "done"
                if item["id"] == interviewer_turn.question_id:
                    item["status"] = "asked"

    return mutate_session(interview_dir, session_id, apply)


def end_with_debrief(
    interview_dir: Path | str,
    session_id: str,
    debrief: InterviewDebrief,
    skill_uses: list[SkillUse] | None = None,
) -> dict:
    def apply(session: dict) -> None:
        if session["status"] != "active":
            raise ValueError("session ended")
        session["status"] = "ended"
        session["ended_at"] = _now()
        session["debrief"] = debrief.model_dump(mode="json")
        if skill_uses:
            session["skill_uses"].extend(
                SkillUse.model_validate(use).model_dump(mode="json") for use in skill_uses
            )
        for item in session["plan"]:
            if item["status"] == "asked":
                item["status"] = "done"

    return mutate_session(interview_dir, session_id, apply)


def archive_session(interview_dir: Path | str, session_id: str) -> dict:
    return _STORE.archive(interview_dir, session_id)


def unarchive_session(interview_dir: Path | str, session_id: str) -> dict:
    return _STORE.unarchive(interview_dir, session_id)


def delete_session(interview_dir: Path | str, session_id: str) -> None:
    """Permanently remove a session; deleting an active session abandons it."""
    with interview_lock():
        session = load_session(interview_dir, session_id)
        _STORE.delete(interview_dir, session_id)
        _delete_audio_artifacts(interview_dir, session)


def rename_session(interview_dir: Path | str, session_id: str, title: str) -> dict:
    return _STORE.rename(interview_dir, session_id, title)


def delete_sessions_for_job(interview_dir: Path | str, job_id: int) -> int:
    """Remove all interview session files for a deleted job. Returns count removed."""
    removed = 0
    with interview_lock():
        for session in list_sessions(interview_dir, include_archived=True):
            if session["job_id"] != job_id:
                continue
            _STORE.delete(interview_dir, session["session_id"])
            _delete_audio_artifacts(interview_dir, session)
            removed += 1
    return removed
