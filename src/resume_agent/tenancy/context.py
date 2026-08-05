from __future__ import annotations

import contextvars
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from resume_agent.tenancy.workspace import WorkspacePaths

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy.engine import Engine

    from resume_agent.config import Settings


@dataclass(frozen=True)
class UserContext:
    user_id: str
    username: str
    role: str
    paths: WorkspacePaths
    settings: Settings = field(repr=False)
    engine: Engine | None
    system_engine: Engine | None
    own_key_providers: frozenset[str]
    platform_provider_keys: dict[str, str] = field(default_factory=dict, repr=False)
    user_provider_keys: dict[str, str] = field(default_factory=dict, repr=False)
    selected_own_key_providers: dict[str, bool] = field(
        default_factory=dict, repr=False, compare=False
    )
    selected_model_own_keys: dict[int, bool] = field(
        default_factory=dict, repr=False, compare=False
    )
    # SpendGate decisions, keyed by model id. Values are ``spend._CachedDecision``
    # at runtime; typed as ``object`` here (rather than importing that type) to
    # avoid a cycle with ``tenancy.spend``, which already imports ``UserContext``.
    # The cache lives on the context rather than in a module global because a
    # context *is* a phase — one request, or one run worker — so the decision
    # expires with the thing it was resolved for, and no test can inherit
    # another test's budget state.
    spend_decisions: dict[str, object] = field(
        default_factory=dict, repr=False, compare=False
    )

    @property
    def workspace(self) -> Path:
        return self.paths.root

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


_current: contextvars.ContextVar[UserContext | None] = contextvars.ContextVar(
    "resume_agent_user_context", default=None
)


def current_context() -> UserContext | None:
    return _current.get()


def require_context() -> UserContext:
    context = current_context()
    if context is None:
        raise RuntimeError("no active UserContext")
    return context


@contextmanager
def use_context(context: UserContext) -> Iterator[UserContext]:
    token = _current.set(context)
    try:
        yield context
    finally:
        _current.reset(token)


def activate(context: UserContext) -> contextvars.Token[UserContext | None]:
    return _current.set(context)


def deactivate(token: contextvars.Token[UserContext | None]) -> None:
    _current.reset(token)


def new_user_id() -> str:
    return uuid.uuid4().hex[:12]
