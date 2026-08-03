"""Durable custody and lifecycle helpers for Career Lab transcripts."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from resume_agent.career_lab.models import (
    CareerLabArtifactMeta,
    CareerLabContextRefs,
    CareerLabSession,
)
from resume_agent.career_skills.models import AgentRunMeta, SkillRef
from resume_agent.sessions.store import SessionStore, now_iso

store = SessionStore(CareerLabSession, label="career lab")


def create_session(
    root: Path | str,
    *,
    session_id: str | None = None,
    goal: str = "",
    title: str = "",
) -> dict:
    """Create one active session, rejecting a second active transcript."""
    with store.lock():
        if store.active(root):
            raise ValueError("an active Career Lab session already exists")
        session = CareerLabSession(
            session_id=session_id or uuid.uuid4().hex,
            started_at=now_iso(),
            goal=goal.strip(),
            title=(title.strip() or goal.strip())[:120],
        )
        store.write(root, session.model_dump(mode="json"))
        return store.load(root, session.session_id)


def load_session(root: Path | str, session_id: str) -> dict:
    return store.load(root, session_id)


def list_sessions(root: Path | str, *, include_archived: bool = False) -> list[dict]:
    return store.list(root, include_archived=include_archived)


def active_session(root: Path | str) -> dict | None:
    rows = store.active(root)
    return rows[0] if rows else None


def rename_session(root: Path | str, session_id: str, title: str) -> dict:
    """Change only the user-facing thread title, preserving its agent goal."""
    cleaned = title.strip()
    if not cleaned:
        raise ValueError("title is empty")
    if len(cleaned) > 120:
        raise ValueError("title is too large")

    def apply(session: dict) -> None:
        session["title"] = cleaned

    return store.mutate(root, session_id, apply)


def append_turns(
    root: Path | str,
    session_id: str,
    *,
    user_text: str,
    context_refs: CareerLabContextRefs | dict[str, Any] | None,
    assistant_text: str,
    skill_ref: SkillRef,
    agent_meta: AgentRunMeta,
    artifact: CareerLabArtifactMeta | None = None,
    notice: str = "",
) -> dict:
    """Validate both turns and commit them in one atomic session mutation."""
    user = user_text.strip()
    if not user:
        raise ValueError("message is empty")
    if len(user) > 100_000:
        raise ValueError("message is too large")
    assistant = assistant_text.strip()
    if not assistant:
        raise ValueError("assistant message is empty")
    refs = (
        context_refs
        if isinstance(context_refs, CareerLabContextRefs)
        else CareerLabContextRefs.model_validate(context_refs or {})
    )
    with store.lock():
        session = store.load(root, session_id)
        if session["status"] != "active":
            raise ValueError("session ended")
        first_id = f"t{len(session['turns']) + 1}"
        second_id = f"t{len(session['turns']) + 2}"
        at = now_iso()
        from resume_agent.career_lab.models import CareerLabTurnRecord

        user_turn = CareerLabTurnRecord(
            turn_id=first_id,
            role="user",
            text=user,
            at=at,
            context_refs=refs,
        )
        assistant_turn = CareerLabTurnRecord(
            turn_id=second_id,
            role="assistant",
            text=assistant,
            at=at,
            skill_ref=skill_ref,
            agent_meta=agent_meta,
            artifact=artifact,
            notice=notice,
        )
        session["turns"].extend(
            [
                user_turn.model_dump(mode="json"),
                assistant_turn.model_dump(mode="json"),
            ]
        )
        store.write(root, session)
        return store.load(root, session_id)


def end_session(root: Path | str, session_id: str) -> dict:
    def apply(session: dict) -> None:
        if session["status"] != "active":
            raise ValueError("session ended")
        session["status"] = "ended"
        session["ended_at"] = now_iso()

    return store.mutate(root, session_id, apply)


def archive_session(root: Path | str, session_id: str) -> dict:
    return store.archive(root, session_id)


def unarchive_session(root: Path | str, session_id: str) -> dict:
    return store.unarchive(root, session_id)


def delete_session(root: Path | str, session_id: str) -> None:
    store.delete(root, session_id)
