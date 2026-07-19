"""Durable Profile Coach sessions with delta-under-lock mutations."""

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
from resume_agent.profile.interview import ResearchAction
from resume_agent.progress import atomic_write_text

_COACH_LOCK = threading.RLock()
_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


class CoachTopic(ExtensibleModel):
    id: str = ""
    gap: str = ""
    why_it_matters: str = ""
    related_ref: str = ""
    status: Literal["open", "drafted", "saved", "skipped"] = "open"
    note_doc_id: str | None = None


class CoachDraftNote(ExtensibleModel):
    topic_id: str = ""
    title: str = ""
    summary: str = ""
    quotes: list[str] = Field(default_factory=list)
    status: Literal["pending", "saved", "discarded"] = "pending"


class CoachTurnRecord(ExtensibleModel):
    role: Literal["coach", "user"] = "user"
    kind: Literal["question", "draft_note", "recap", ""] = ""
    text: str = ""
    topic_id: str = ""
    at: str = ""
    research_actions: list[ResearchAction] = Field(default_factory=list)


class CoachSession(ExtensibleModel):
    session_id: str = ""
    started_at: str = ""
    ended_at: str | None = None
    status: Literal["active", "ended"] = "active"
    archived_at: str | None = None
    turns: list[CoachTurnRecord] = Field(default_factory=list)
    topics: list[CoachTopic] = Field(default_factory=list)
    draft_notes: list[CoachDraftNote] = Field(default_factory=list)
    recap: str | None = None
    impact: dict | None = None


def coach_dir(profile_dir: Path | str) -> Path:
    return Path(profile_dir) / "coach"


def _valid_session_id(session_id: str) -> bool:
    return bool(_SESSION_ID.fullmatch(session_id))


def _session_path(profile_dir: Path | str, session_id: str) -> Path:
    if not _valid_session_id(session_id):
        raise ValueError(f"unknown session: {session_id}")
    return coach_dir(profile_dir) / f"session-{session_id}.json"


@contextmanager
def coach_lock() -> Iterator[None]:
    """Serialize coach session and approval mutations in this process."""
    with _COACH_LOCK:
        yield


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return CoachSession.model_validate(raw).model_dump(mode="json")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid coach session: {path}") from exc


def _write(profile_dir: Path | str, session: dict) -> None:
    validated = CoachSession.model_validate(session)
    if not _valid_session_id(validated.session_id):
        raise ValueError("invalid session id")
    atomic_write_text(
        _session_path(profile_dir, validated.session_id),
        validated.model_dump_json(indent=2) + "\n",
    )


def list_sessions(
    profile_dir: Path | str, *, include_archived: bool = False
) -> list[dict]:
    root = coach_dir(profile_dir)
    if not root.exists():
        return []
    sessions = [_read(path) for path in root.glob("session-*.json")]
    if not include_archived:
        sessions = [row for row in sessions if not row["archived_at"]]
    return sorted(sessions, key=lambda row: (row["started_at"], row["session_id"]))


def load_session(profile_dir: Path | str, session_id: str) -> dict:
    path = _session_path(profile_dir, session_id)
    if not path.exists():
        raise ValueError(f"unknown session: {session_id}")
    return _read(path)


def active_session(profile_dir: Path | str) -> dict | None:
    return next(
        (session for session in list_sessions(profile_dir) if session["status"] == "active"),
        None,
    )


def create_session(
    profile_dir: Path | str,
    session_id: str,
    topics: list[CoachTopic],
    opening_turn: CoachTurnRecord,
) -> None:
    if not _valid_session_id(session_id):
        raise ValueError("invalid session id")
    with coach_lock():
        if active_session(profile_dir) is not None:
            raise ValueError("active session exists")
        topic_ids = [topic.id for topic in topics]
        if not topics or len(topic_ids) != len(set(topic_ids)):
            raise ValueError("invalid coach topics")
        if opening_turn.topic_id not in set(topic_ids):
            raise ValueError("opening turn references unknown topic")
        now = _now()
        _write(
            profile_dir,
            CoachSession(
                session_id=session_id,
                started_at=now,
                turns=[opening_turn.model_copy(update={"at": now})],
                topics=topics,
            ).model_dump(mode="json"),
        )


def mutate_session(
    profile_dir: Path | str,
    session_id: str,
    fn: Callable[[dict], None],
) -> dict:
    with coach_lock():
        session = load_session(profile_dir, session_id)
        fn(session)
        _write(profile_dir, session)
        return load_session(profile_dir, session_id)


def apply_turn_delta(
    profile_dir: Path | str,
    session_id: str,
    *,
    user_text: str,
    coach_turn: CoachTurnRecord,
    new_topics: list[CoachTopic],
    skipped_topic_ids: list[str],
    draft: CoachDraftNote | None,
) -> dict:
    def apply(session: dict) -> None:
        if session["status"] != "active":
            raise ValueError("session ended")
        existing_ids = {topic["id"] for topic in session["topics"]}
        new_ids = [topic.id for topic in new_topics]
        if existing_ids.intersection(new_ids) or len(new_ids) != len(set(new_ids)):
            raise ValueError("duplicate topic id")
        if draft is not None and any(
            row["topic_id"] == draft.topic_id for row in session["draft_notes"]
        ):
            raise ValueError("draft already exists")
        now = _now()
        session["turns"].append(
            CoachTurnRecord(
                role="user",
                text=user_text,
                topic_id=coach_turn.topic_id,
                at=now,
            ).model_dump(mode="json")
        )
        session["turns"].append(
            coach_turn.model_copy(update={"at": now}).model_dump(mode="json")
        )
        session["topics"].extend(topic.model_dump(mode="json") for topic in new_topics)
        for topic in session["topics"]:
            if topic["id"] in skipped_topic_ids and topic["status"] == "open":
                topic["status"] = "skipped"
            if draft is not None and topic["id"] == draft.topic_id:
                topic["status"] = "drafted"
        if draft is not None:
            session["draft_notes"].append(draft.model_dump(mode="json"))

    return mutate_session(profile_dir, session_id, apply)


def set_draft_status(
    profile_dir: Path | str,
    session_id: str,
    topic_id: str,
    status: Literal["saved", "discarded"],
    note_doc_id: str | None = None,
) -> dict:
    def apply(session: dict) -> None:
        draft = next(
            (row for row in session["draft_notes"] if row["topic_id"] == topic_id),
            None,
        )
        if draft is None:
            raise ValueError(f"unknown draft: {topic_id}")
        if draft["status"] != "pending":
            raise ValueError("draft already resolved")
        draft["status"] = status
        for topic in session["topics"]:
            if topic["id"] == topic_id:
                topic["status"] = "saved" if status == "saved" else "skipped"
                topic["note_doc_id"] = note_doc_id

    return mutate_session(profile_dir, session_id, apply)


def end_session(profile_dir: Path | str, session_id: str, recap: str) -> dict:
    def apply(session: dict) -> None:
        if session["status"] != "active":
            raise ValueError("session ended")
        now = _now()
        session["status"] = "ended"
        session["ended_at"] = now
        session["recap"] = recap
        session["turns"].append(
            CoachTurnRecord(role="coach", kind="recap", text=recap, at=now).model_dump(mode="json")
        )

    return mutate_session(profile_dir, session_id, apply)


def archive_session(profile_dir: Path | str, session_id: str) -> dict:
    def apply(session: dict) -> None:
        if session["status"] != "ended":
            raise ValueError("only ended sessions can be archived")
        if session["archived_at"]:
            raise ValueError("session already archived")
        session["archived_at"] = _now()

    return mutate_session(profile_dir, session_id, apply)


def unarchive_session(profile_dir: Path | str, session_id: str) -> dict:
    def apply(session: dict) -> None:
        if not session["archived_at"]:
            raise ValueError("session not archived")
        session["archived_at"] = None

    return mutate_session(profile_dir, session_id, apply)


def delete_session(profile_dir: Path | str, session_id: str) -> None:
    """Remove the transcript record without touching saved profile notes."""
    with coach_lock():
        path = _session_path(profile_dir, session_id)
        if not path.exists():
            raise ValueError(f"unknown session: {session_id}")
        path.unlink()


def set_impact(profile_dir: Path | str, session_id: str, impact: dict) -> dict:
    return mutate_session(
        profile_dir,
        session_id,
        lambda session: session.__setitem__("impact", impact),
    )
