"""Durable Mock Interview sessions with delta-under-lock mutations."""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import Field

from resume_agent.models.base import ExtensibleModel
from resume_agent.progress import atomic_write_text

_INTERVIEW_LOCK = threading.RLock()
_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")

STYLE_EXTRA_CAP = 2_000


class InterviewStyle(ExtensibleModel):
    stage: Literal[
        "recruiter_screen", "hiring_manager", "technical", "behavioral"
    ] = "hiring_manager"
    demeanor: Literal["warm", "neutral", "stress"] = "neutral"
    difficulty: Literal["easy", "standard", "hard"] = "standard"
    question_count: int = Field(default=8, ge=4, le=12)
    extra: str = Field(default="", max_length=STYLE_EXTRA_CAP)


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


class InterviewSession(ExtensibleModel):
    session_id: str = ""
    job_id: int = 0
    resume_version_id: int = 0
    started_at: str = ""
    ended_at: str | None = None
    status: Literal["active", "ended"] = "active"
    concluded: bool = False
    archived_at: str | None = None
    style: InterviewStyle = Field(default_factory=InterviewStyle)
    context: InterviewContext = Field(default_factory=InterviewContext)
    plan: list[PlanItem] = Field(default_factory=list)
    turns: list[InterviewTurnRecord] = Field(default_factory=list)
    debrief: InterviewDebrief | None = None


def _valid_session_id(session_id: str) -> bool:
    return bool(_SESSION_ID.fullmatch(session_id))


def _session_path(interview_dir: Path | str, session_id: str) -> Path:
    if not _valid_session_id(session_id):
        raise ValueError(f"unknown session: {session_id}")
    return Path(interview_dir) / f"session-{session_id}.json"


@contextmanager
def interview_lock() -> Iterator[None]:
    """Serialize interview session mutations in this process."""
    with _INTERVIEW_LOCK:
        yield


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return InterviewSession.model_validate(raw).model_dump(mode="json")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid interview session: {path}") from exc


def _write(interview_dir: Path | str, session: dict) -> None:
    validated = InterviewSession.model_validate(session)
    if not _valid_session_id(validated.session_id):
        raise ValueError("invalid session id")
    atomic_write_text(
        _session_path(interview_dir, validated.session_id),
        validated.model_dump_json(indent=2) + "\n",
    )


def list_sessions(
    interview_dir: Path | str,
    job_id: int | None = None,
    *,
    include_archived: bool = False,
) -> list[dict]:
    root = Path(interview_dir)
    if not root.exists():
        return []
    sessions = [_read(path) for path in root.glob("session-*.json")]
    if job_id is not None:
        sessions = [row for row in sessions if row["job_id"] == job_id]
    if not include_archived:
        sessions = [row for row in sessions if not row["archived_at"]]
    return sorted(sessions, key=lambda row: (row["started_at"], row["session_id"]))


def load_session(interview_dir: Path | str, session_id: str) -> dict:
    path = _session_path(interview_dir, session_id)
    if not path.exists():
        raise ValueError(f"unknown session: {session_id}")
    return _read(path)


def active_sessions(interview_dir: Path | str) -> list[dict]:
    return [
        row for row in list_sessions(interview_dir) if row["status"] == "active"
    ]


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
            ).model_dump(mode="json"),
        )


def mutate_session(
    interview_dir: Path | str,
    session_id: str,
    fn: Callable[[dict], None],
) -> dict:
    with interview_lock():
        session = load_session(interview_dir, session_id)
        fn(session)
        _write(interview_dir, session)
        return load_session(interview_dir, session_id)


def apply_answer_delta(
    interview_dir: Path | str,
    session_id: str,
    *,
    answer_text: str,
    interviewer_turn: InterviewTurnRecord,
    concluded: bool,
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
) -> dict:
    def apply(session: dict) -> None:
        if session["status"] != "active":
            raise ValueError("session ended")
        session["status"] = "ended"
        session["ended_at"] = _now()
        session["debrief"] = debrief.model_dump(mode="json")
        for item in session["plan"]:
            if item["status"] == "asked":
                item["status"] = "done"

    return mutate_session(interview_dir, session_id, apply)


def archive_session(interview_dir: Path | str, session_id: str) -> dict:
    def apply(session: dict) -> None:
        if session["status"] != "ended":
            raise ValueError("only ended sessions can be archived")
        if session["archived_at"]:
            raise ValueError("session already archived")
        session["archived_at"] = _now()

    return mutate_session(interview_dir, session_id, apply)


def unarchive_session(interview_dir: Path | str, session_id: str) -> dict:
    def apply(session: dict) -> None:
        if not session["archived_at"]:
            raise ValueError("session not archived")
        session["archived_at"] = None

    return mutate_session(interview_dir, session_id, apply)


def delete_session(interview_dir: Path | str, session_id: str) -> None:
    """Permanently remove a session; deleting an active session abandons it."""
    with interview_lock():
        path = _session_path(interview_dir, session_id)
        if not path.exists():
            raise ValueError(f"unknown session: {session_id}")
        path.unlink()


def delete_sessions_for_job(interview_dir: Path | str, job_id: int) -> int:
    """Remove all interview session files for a deleted job. Returns count removed."""
    removed = 0
    with interview_lock():
        for row in list_sessions(
            interview_dir, job_id=job_id, include_archived=True
        ):
            _session_path(interview_dir, row["session_id"]).unlink(missing_ok=True)
            removed += 1
    return removed
