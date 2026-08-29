"""Durable Profile Coach sessions with delta-under-lock mutations."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Literal

from pydantic import Field

from resume_agent.models.base import ExtensibleModel
from resume_agent.profile.interview import ResearchAction
from resume_agent.sessions.store import (
    SessionModel,
    SessionStore,
    now_iso,
    valid_session_id,
)


class CoachTopic(ExtensibleModel):
    id: str = ""
    gap: str = ""
    why_it_matters: str = ""
    related_ref: str = ""
    owner_id: str = ""
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
    notice: str = ""
    research_actions: list[ResearchAction] = Field(default_factory=list)


class CoachSession(SessionModel):
    ended_at: str | None = None
    turns: list[CoachTurnRecord] = Field(default_factory=list)
    topics: list[CoachTopic] = Field(default_factory=list)
    draft_notes: list[CoachDraftNote] = Field(default_factory=list)
    recap: str | None = None
    impact: dict | None = None


_STORE: SessionStore[CoachSession] = SessionStore(CoachSession, label="coach")


def coach_dir(profile_dir: Path | str) -> Path:
    return Path(profile_dir) / "coach"


def _valid_session_id(session_id: str) -> bool:
    return valid_session_id(session_id)


def coach_lock() -> AbstractContextManager[None]:
    """Serialize coach session and approval mutations in this process."""
    return _STORE.lock()


def _now() -> str:
    return now_iso()


def _write(profile_dir: Path | str, session: dict) -> None:
    _STORE.write(coach_dir(profile_dir), session)


def list_sessions(
    profile_dir: Path | str, *, include_archived: bool = False
) -> list[dict]:
    return _STORE.list(coach_dir(profile_dir), include_archived=include_archived)


def load_session(profile_dir: Path | str, session_id: str) -> dict:
    return _STORE.load(coach_dir(profile_dir), session_id)


def active_session(profile_dir: Path | str) -> dict | None:
    return next(iter(_STORE.active(coach_dir(profile_dir))), None)


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
    return _STORE.mutate(coach_dir(profile_dir), session_id, fn)


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


def end_session(
    profile_dir: Path | str, session_id: str, recap: str, *, notice: str = ""
) -> dict:
    def apply(session: dict) -> None:
        if session["status"] != "active":
            raise ValueError("session ended")
        now = _now()
        session["status"] = "ended"
        session["ended_at"] = now
        session["recap"] = recap
        session["turns"].append(
            CoachTurnRecord(
                role="coach", kind="recap", text=recap, at=now, notice=notice
            ).model_dump(mode="json")
        )

    return mutate_session(profile_dir, session_id, apply)


def archive_session(profile_dir: Path | str, session_id: str) -> dict:
    return _STORE.archive(coach_dir(profile_dir), session_id)


def unarchive_session(profile_dir: Path | str, session_id: str) -> dict:
    return _STORE.unarchive(coach_dir(profile_dir), session_id)


def delete_session(profile_dir: Path | str, session_id: str) -> None:
    """Remove the transcript record without touching saved profile notes."""
    _STORE.delete(coach_dir(profile_dir), session_id)


def rename_session(profile_dir: Path | str, session_id: str, title: str) -> dict:
    return _STORE.rename(coach_dir(profile_dir), session_id, title)


def set_impact(profile_dir: Path | str, session_id: str, impact: dict) -> dict:
    return mutate_session(
        profile_dir,
        session_id,
        lambda session: session.__setitem__("impact", impact),
    )
