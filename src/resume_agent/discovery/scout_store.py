"""Durable Discovery Scout sessions and locked proposal mutations."""

from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from resume_agent.discovery.scout import (
    PENDING_CAP,
    PROPOSAL_CAP,
    SENIORITY_VALUES,
    SuggestionKind,
)
from resume_agent.discovery.scout_models import Citation
from resume_agent.models.base import ExtensibleModel
from resume_agent.sessions.store import SessionModel, SessionStore, now_iso


class SourcePayload(ExtensibleModel):
    company: str = ""
    url: str = ""
    ats: str | None = None
    token: str | None = None
    role_count: int | None = None
    error_code: str | None = None


class TermPayload(ExtensibleModel):
    value: str = ""
    term_kind: SuggestionKind = "keyword"

    @model_validator(mode="after")
    def validate_seniority(self) -> Self:
        if self.term_kind == "seniority" and self.value.casefold() not in SENIORITY_VALUES:
            raise ValueError("seniority must use the configured experience-level vocabulary")
        return self


class ScoutProposal(ExtensibleModel):
    id: str = ""
    kind: Literal["source", "search_term"] = "source"
    source: SourcePayload | None = None
    term: TermPayload | None = None
    reason: str = ""
    fit_score: int | None = Field(default=None, ge=0, le=100)
    citations: list[Citation] = Field(default_factory=list)
    check: Literal["validated", "unverified", "failed", "duplicate", "avoid", "new"] = "new"
    check_error: str = ""
    status: Literal["pending", "added", "dismissed"] = "pending"
    dismiss_reason: str = ""
    resolved_at: str | None = None

    @model_validator(mode="after")
    def exactly_one_payload(self) -> Self:
        if (self.source is None) == (self.term is None):
            raise ValueError("exactly one proposal payload is required")
        if self.kind == "source" and self.source is None:
            raise ValueError("source proposal requires source payload")
        if self.kind == "search_term" and self.term is None:
            raise ValueError("search-term proposal requires term payload")
        return self


class ScoutTurnRecord(ExtensibleModel):
    role: Literal["scout", "user"] = "user"
    kind: Literal["reply", "recap", ""] = ""
    text: str = ""
    at: str = ""
    notice: str = ""
    proposal_ids: list[str] = Field(default_factory=list)


class ScoutSession(SessionModel):
    goal: str = ""
    turns: list[ScoutTurnRecord] = Field(default_factory=list)
    proposals: list[ScoutProposal] = Field(default_factory=list)
    recap: str | None = None
    ended_at: str | None = None


_STORE: SessionStore[ScoutSession] = SessionStore(ScoutSession, label="scout")


def scout_dir(workspace_root: Path | str) -> Path:
    return Path(workspace_root) / "scout"


def scout_lock() -> AbstractContextManager[None]:
    return _STORE.lock()


def load_session(workspace_root: Path | str, session_id: str) -> dict:
    return _STORE.load(scout_dir(workspace_root), session_id)


def list_sessions(
    workspace_root: Path | str, *, include_archived: bool = False
) -> list[dict]:
    return _STORE.list(scout_dir(workspace_root), include_archived=include_archived)


def active_session(workspace_root: Path | str) -> dict | None:
    return next(iter(_STORE.active(scout_dir(workspace_root))), None)


def _append_turn(
    session: dict,
    *,
    user_text: str,
    scout_turn: ScoutTurnRecord,
    proposals: list[ScoutProposal],
    goal_update: str | None = None,
) -> None:
    if session["status"] != "active":
        raise ValueError("session ended")
    if len(proposals) > PROPOSAL_CAP:
        raise ValueError(f"a turn may contain at most {PROPOSAL_CAP} proposals")
    pending = sum(row["status"] == "pending" for row in session["proposals"])
    if pending + len(proposals) > PENDING_CAP:
        raise ValueError(f"a session may contain at most {PENDING_CAP} pending proposals")
    now = now_iso()
    first_id = len(session["proposals"]) + 1
    stored = [
        proposal.model_copy(update={"id": f"p{first_id + offset}"})
        for offset, proposal in enumerate(proposals)
    ]
    proposal_ids = [proposal.id for proposal in stored]
    session["turns"].extend(
        [
            ScoutTurnRecord(role="user", text=user_text, at=now).model_dump(mode="json"),
            scout_turn.model_copy(update={"at": now, "proposal_ids": proposal_ids}).model_dump(mode="json"),
        ]
    )
    session["proposals"].extend(row.model_dump(mode="json") for row in stored)
    if goal_update is not None:
        session["goal"] = goal_update


def create_session_from_turn(
    workspace_root: Path | str,
    session_id: str,
    *,
    goal: str,
    user_text: str,
    scout_turn: ScoutTurnRecord,
    proposals: list[ScoutProposal],
) -> dict:
    with scout_lock():
        if active_session(workspace_root) is not None:
            raise ValueError("active session exists")
        session = ScoutSession(
            session_id=session_id,
            started_at=now_iso(),
            goal=goal,
        ).model_dump(mode="json")
        _append_turn(
            session,
            user_text=user_text,
            scout_turn=scout_turn,
            proposals=proposals,
        )
        _STORE.write(scout_dir(workspace_root), session)
        return load_session(workspace_root, session_id)


def apply_turn_delta(
    workspace_root: Path | str,
    session_id: str,
    *,
    user_text: str,
    scout_turn: ScoutTurnRecord,
    proposals: list[ScoutProposal],
    goal_update: str | None = None,
) -> dict:
    def apply(session: dict) -> None:
        _append_turn(
            session,
            user_text=user_text,
            scout_turn=scout_turn,
            proposals=proposals,
            goal_update=goal_update,
        )

    return _STORE.mutate(scout_dir(workspace_root), session_id, apply)


def set_proposal_status(
    workspace_root: Path | str,
    session_id: str,
    proposal_id: str,
    status: Literal["added", "dismissed"],
    *,
    reason: str = "",
) -> dict:
    def apply(session: dict) -> None:
        proposal = next((row for row in session["proposals"] if row["id"] == proposal_id), None)
        if proposal is None:
            raise ValueError(f"unknown proposal: {proposal_id}")
        if proposal["status"] != "pending":
            raise ValueError("proposal already resolved")
        proposal["status"] = status
        proposal["dismiss_reason"] = reason if status == "dismissed" else ""
        proposal["resolved_at"] = now_iso()

    return _STORE.mutate(scout_dir(workspace_root), session_id, apply)


def end_session(
    workspace_root: Path | str, session_id: str, recap: str, *, notice: str = ""
) -> dict:
    def apply(session: dict) -> None:
        if session["status"] != "active":
            raise ValueError("session ended")
        now = now_iso()
        session["status"] = "ended"
        session["ended_at"] = now
        session["recap"] = recap
        session["turns"].append(
            ScoutTurnRecord(
                role="scout", kind="recap", text=recap, at=now, notice=notice
            ).model_dump(mode="json")
        )

    return _STORE.mutate(scout_dir(workspace_root), session_id, apply)


def archive_session(workspace_root: Path | str, session_id: str) -> dict:
    return _STORE.archive(scout_dir(workspace_root), session_id)


def unarchive_session(workspace_root: Path | str, session_id: str) -> dict:
    return _STORE.unarchive(scout_dir(workspace_root), session_id)


def delete_session(workspace_root: Path | str, session_id: str) -> None:
    _STORE.delete(scout_dir(workspace_root), session_id)
