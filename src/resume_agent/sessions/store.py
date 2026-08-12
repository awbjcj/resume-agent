"""File custody for durable turn-per-run sessions (ADR-0006).

One SessionStore instance per session kind owns the custody rules the Profile
Coach and Mock Interview stores used to copy: session-id validation, the
``session-<id>.json`` naming scheme, the process-wide mutation lock, validated
atomic read/write, listing with the archived filter and stable sort, active
filtering, delta-under-lock mutation, and the archive/unarchive/delete
lifecycle. Kind-specific behavior — turn schemas, creation invariants, delta
application — stays in the kind's own module.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generic, Literal, TypeVar

from pydantic import Field

from resume_agent.models.base import ExtensibleModel
from resume_agent.progress import atomic_write_text

logger = logging.getLogger(__name__)

_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


class SessionModel(ExtensibleModel):
    """Fields every session-store model must define: id, start time, lifecycle, archival."""

    session_id: str = ""
    session_title: str = Field(default="", max_length=120)
    started_at: str = ""
    status: Literal["active", "ended"] = "active"
    archived_at: str | None = None


M = TypeVar("M", bound=SessionModel)


def valid_session_id(session_id: str) -> bool:
    return bool(_SESSION_ID.fullmatch(session_id))


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SessionStore(Generic[M]):
    """Custody for one session kind's files under a resolved root directory.

    ``model`` must define ``session_id``, ``started_at``, ``status`` (with
    ``"active"``/``"ended"`` among its values), and ``archived_at``.
    """

    def __init__(self, model: type[M], *, label: str) -> None:
        self.model = model
        self.label = label
        self._lock = threading.RLock()

    @contextmanager
    def lock(self) -> Iterator[None]:
        """Serialize this kind's session mutations in this process."""
        with self._lock:
            yield

    def path(self, root: Path | str, session_id: str) -> Path:
        if not valid_session_id(session_id):
            raise ValueError(f"unknown session: {session_id}")
        return Path(root) / f"session-{session_id}.json"

    def read(self, path: Path) -> dict:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return self.model.model_validate(raw).model_dump(mode="json")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid {self.label} session: {path}") from exc

    def write(self, root: Path | str, session: dict) -> None:
        validated = self.model.model_validate(session)
        session_id = validated.session_id
        if not valid_session_id(session_id):
            raise ValueError("invalid session id")
        atomic_write_text(
            self.path(root, session_id),
            validated.model_dump_json(indent=2) + "\n",
        )

    def list(self, root: Path | str, *, include_archived: bool = False) -> list[dict]:
        """Every readable session, oldest first.

        An unreadable file is skipped with a warning rather than failing the
        whole enumeration. ``load`` stays strict — asking for one session by id
        must say so when it cannot be read — but one corrupt file must not take
        down every listing, active-session check and bulk delete in the
        workspace. That failure mode was live: a job delete ran its cascade
        after the row was already committed, so a single bad file turned every
        future delete into a 500 on a job that had in fact been removed.
        """
        base = Path(root)
        if not base.exists():
            return []
        sessions = []
        for path in base.glob("session-*.json"):
            try:
                sessions.append(self.read(path))
            except ValueError:
                logger.warning("Skipping unreadable %s session: %s", self.label, path)
        if not include_archived:
            sessions = [row for row in sessions if not row["archived_at"]]
        return sorted(sessions, key=lambda row: (row["started_at"], row["session_id"]))

    def load(self, root: Path | str, session_id: str) -> dict:
        path = self.path(root, session_id)
        if not path.exists():
            raise ValueError(f"unknown session: {session_id}")
        return self.read(path)

    def active(self, root: Path | str) -> list[dict]:
        return [row for row in self.list(root) if row["status"] == "active"]

    def mutate(
        self, root: Path | str, session_id: str, fn: Callable[[dict], None]
    ) -> dict:
        with self.lock():
            session = self.load(root, session_id)
            fn(session)
            self.write(root, session)
            return self.load(root, session_id)

    def archive(self, root: Path | str, session_id: str) -> dict:
        def apply(session: dict) -> None:
            if session["status"] != "ended":
                raise ValueError("only ended sessions can be archived")
            if session["archived_at"]:
                raise ValueError("session already archived")
            session["archived_at"] = now_iso()

        return self.mutate(root, session_id, apply)

    def unarchive(self, root: Path | str, session_id: str) -> dict:
        def apply(session: dict) -> None:
            if not session["archived_at"]:
                raise ValueError("session not archived")
            session["archived_at"] = None

        return self.mutate(root, session_id, apply)

    def delete(self, root: Path | str, session_id: str) -> None:
        with self.lock():
            path = self.path(root, session_id)
            if not path.exists():
                raise ValueError(f"unknown session: {session_id}")
            path.unlink()

    def delete_where(
        self, root: Path | str, predicate: Callable[[dict], bool]
    ) -> int:
        """Remove every session matching ``predicate``. Returns how many went.

        Bulk removal is custody, not kind-specific behavior: the lock must span
        the scan and the unlinks so a session created in between cannot survive
        as an orphan, archived rows must be included or they outlive their owner,
        and a file that vanishes underneath us is the outcome asked for rather
        than an error. Only the predicate belongs to the kind.
        """
        removed = 0
        with self.lock():
            for row in self.list(root, include_archived=True):
                if not predicate(row):
                    continue
                self.path(root, row["session_id"]).unlink(missing_ok=True)
                removed += 1
        return removed

    def rename(self, root: Path | str, session_id: str, title: str) -> dict:
        cleaned = title.strip()
        if not cleaned:
            raise ValueError("session title is empty")
        if len(cleaned) > 120:
            raise ValueError("session title is too large")

        return self.mutate(
            root,
            session_id,
            lambda session: session.__setitem__("session_title", cleaned),
        )
