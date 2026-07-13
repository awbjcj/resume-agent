# Multi-User Tenancy — Plan 1: Tenancy Core + Migration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `UserContext` tenancy seam (contextvar-propagated, ADR-0003), per-user Workspaces under `data/users/<id>/`, the shared `system.db` with the `users` table, engine registry, legacy-root adoption, and CLI workspace resolution — leaving the app functionally single-user but running on multi-user plumbing.

**Architecture:** One new package `src/resume_agent/tenancy/` holds the whole seam. A `contextvars.ContextVar` carries the active `UserContext`; `get_settings()` consults it and falls back to env settings (so the 36 domain-layer call sites do not change). System tables use their own SQLAlchemy `DeclarativeBase` — never SQLModel's global metadata — so `create_all` on a workspace engine cannot leak system tables into workspace DBs and vice versa. Spec: `docs/superpowers/specs/2026-07-12-multi-user-tenancy-design.md`; decision record: `docs/adr/0003-contextvar-tenancy-propagation.md`.

**Tech Stack:** Python 3.12, FastAPI, SQLModel (workspace DB) + plain SQLAlchemy 2.x ORM (system DB), pydantic-settings, typer, pytest (offline — no network, no API keys).

## Correctness amendments (audit before implementation)

These corrections are part of the plan and override later reference snippets:

- Use the repository runtime contract (Python **3.13+**), not the stale 3.12
  label above.
- Every file-backed `create_app` boots multi-user and refuses an empty user
  table without seed credentials. The only legacy boot is the in-memory
  SQLite test adapter; do not key production mode on whether credentials
  happen to be present.
- Expand `UserContext` to carry typed `WorkspacePaths`, `system_engine`, and
  `own_key_providers`. `build_context` must provision the Workspace
  idempotently before opening its engine.
- Provision every supported `config/*.example` target, not the four-name list;
  direct reliance on `python-dotenv` must either be declared or replaced by
  the repository's existing env parser.
- Legacy adoption needs a journal plus rollback/resume behavior. The simple
  sequence of `shutil.move` calls is not the rollback-safe child swap promised
  by the design. Bootstrap checks whether **any users** exist separately from
  finding an admin; a non-empty/no-admin database is an error, not a reason to
  seed another account.
- Add request-scoped resource adapters for engine, settings, `YamlConfigStore`,
  `DocumentStore`, secrets/env path, and Workspace data/profile paths. Convert
  every guarded router currently reading tenant data through `app.state`
  (`config`, `profile`, `secrets`, `setup`, `runs`, `match_gap`, and
  `suggestions`). Merely leaving `app.state.engine` pointed at the seed admin is
  a cross-tenant data leak after Plan 2 authenticates a different user.
- Store run records under each Workspace `runs/`, register/recover all roots,
  and capture the context on submit. Preserve the legacy root only for the
  in-memory adapter and existing direct `RunManager` unit tests.
- CLI activation must rebase default `data/...` and `config/...` command
  arguments into the selected Workspace while preserving explicit paths.
  Context-aware `get_settings()` alone does not fix literal CLI paths.
- Intermediate verification stays focused per task. Do not run the full suite
  after Tasks 2 and 8 as the optimistic text suggests; save it for the final
  verification phase requested by the user.

## Global Constraints

- **Strict TDD** (superpowers:test-driven-development): every task writes its failing test first and runs it to observe RED before any implementation code; implementation is the minimum to reach GREEN. Never reorder these steps.
- Test command: `.venv/Scripts/python.exe -m pytest` (offline); lint: `ruff check`.
- The workspace job-DB schema does **not** change; isolation is by file, never by column.
- With **no** active context, behavior must be byte-identical to today (env settings, `app.state.engine`) — this keeps the existing ~900-test suite green and is the deliberate escape hatch of ADR-0003.
- In-memory SQLite apps (`sqlite://`, `sqlite:///:memory:`) always boot the legacy single-tenant path — the in-memory StaticPool adapter is a test-only substrate.
- `user_id` is `uuid4().hex[:12]` — opaque, Windows-path-safe, rename-proof.
- Never overwrite an existing file during adoption; adoption is resumable (re-run moves the remainder).
- Commit after every task; messages in the repo's imperative style ("Adds …").

---

### Task 1: UserContext + contextvar

**Files:**

- Create: `src/resume_agent/tenancy/__init__.py` (empty)
- Create: `src/resume_agent/tenancy/context.py`
- Test: `tests/tenancy/__init__.py` (empty), `tests/tenancy/test_context.py`

**Interfaces:**

- Produces: `UserContext` (frozen dataclass: `user_id: str`, `username: str`, `role: str`, `workspace: Path`, `settings: Settings`, `engine: Engine`), `current_context() -> UserContext | None`, `require_context() -> UserContext`, `use_context(ctx)` (context manager), `activate(ctx)` (process-lifetime set, for the CLI), `new_user_id() -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/tenancy/test_context.py
"""UserContext contextvar seam (ADR-0003)."""

import contextvars
import threading
from pathlib import Path

import pytest

from resume_agent.config import Settings
from resume_agent.tenancy.context import (
    UserContext,
    activate,
    current_context,
    new_user_id,
    require_context,
    use_context,
)


def make_ctx(**overrides) -> UserContext:
    defaults = dict(
        user_id="abc123def456",
        username="alice",
        role="user",
        workspace=Path("data/users/abc123def456"),
        settings=Settings(_env_file=None),
        engine=None,  # unit tests never touch the DB
    )
    defaults.update(overrides)
    return UserContext(**defaults)


def test_no_context_by_default():
    assert current_context() is None


def test_use_context_sets_and_resets():
    ctx = make_ctx()
    with use_context(ctx) as active:
        assert active is ctx
        assert current_context() is ctx
    assert current_context() is None


def test_use_context_resets_on_exception():
    ctx = make_ctx()
    with pytest.raises(ValueError):
        with use_context(ctx):
            raise ValueError("boom")
    assert current_context() is None


def test_require_context_raises_without_active():
    with pytest.raises(RuntimeError):
        require_context()


def test_require_context_returns_active():
    ctx = make_ctx()
    with use_context(ctx):
        assert require_context() is ctx


def test_copied_context_carries_user_into_thread():
    """The RunManager propagation contract: copy_context().run in a worker
    thread sees the submitting request's context."""
    ctx = make_ctx(username="bob")
    seen: list[UserContext | None] = []
    with use_context(ctx):
        snapshot = contextvars.copy_context()
    thread = threading.Thread(target=lambda: snapshot.run(lambda: seen.append(current_context())))
    thread.start()
    thread.join()
    assert seen == [ctx]


def test_activate_is_process_lifetime():
    ctx = make_ctx(username="cli-user")
    token = activate(ctx)
    try:
        assert current_context() is ctx
    finally:
        # tests must clean up; the CLI never resets
        from resume_agent.tenancy.context import _current
        _current.reset(token)


def test_new_user_id_shape():
    uid = new_user_id()
    assert len(uid) == 12
    assert uid == uid.lower()
    int(uid, 16)  # hex
    assert new_user_id() != uid
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/tenancy/test_context.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.tenancy'`

- [ ] **Step 3: Implement**

```python
# src/resume_agent/tenancy/context.py
"""The tenancy seam: a contextvar-held UserContext (ADR-0003).

Exactly three places set the context: the API auth dependency (per request),
the RunManager submit wrapper (per background run, via copy_context), and the
CLI entrypoint (per invocation, via activate). Everything user-scoped —
effective settings, workspace paths, the jobs-DB engine — resolves from here.
With no context set, callers fall back to env-derived process-global state,
which is byte-identical to the historical single-user behavior.
"""

from __future__ import annotations

import contextvars
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from resume_agent.config import Settings


@dataclass(frozen=True)
class UserContext:
    """One authenticated user bound to their Workspace for one request/run/invocation."""

    user_id: str
    username: str
    role: str
    workspace: Path
    settings: "Settings"
    engine: "Engine | None"

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


_current: contextvars.ContextVar[UserContext | None] = contextvars.ContextVar(
    "resume_agent_user_context", default=None
)


def current_context() -> UserContext | None:
    return _current.get()


def require_context() -> UserContext:
    ctx = _current.get()
    if ctx is None:
        raise RuntimeError("no active UserContext; this code path requires tenancy")
    return ctx


@contextmanager
def use_context(ctx: UserContext) -> Iterator[UserContext]:
    """Scoped activation — the API dependency's shape."""
    token = _current.set(ctx)
    try:
        yield ctx
    finally:
        _current.reset(token)


def activate(ctx: UserContext) -> contextvars.Token:
    """Process-lifetime activation — the CLI's shape. Returns the token so
    tests can reset; the CLI never does."""
    return _current.set(ctx)


def new_user_id() -> str:
    """Opaque, Windows-path-safe workspace directory name."""
    return uuid.uuid4().hex[:12]
```

Also create the two empty `__init__.py` files.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/tenancy/test_context.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tenancy tests/tenancy
git commit -m "Adds UserContext contextvar seam (ADR-0003)"
```

---

### Task 2: get_settings() consults the active context

**Files:**

- Modify: `src/resume_agent/config.py:51-54`
- Modify: `src/resume_agent/api/routers/admin.py:85` (`get_settings.cache_clear()` call site)
- Modify: `src/resume_agent/services/env_config.py:40` (same)
- Test: `tests/tenancy/test_settings_overlay.py`

**Interfaces:**

- Consumes: `current_context()` from Task 1.
- Produces: `env_settings() -> Settings` (lru_cached, the no-context fallback — replaces the old cached `get_settings` for cache-clearing purposes); `get_settings() -> Settings` keeps its signature but returns `ctx.settings` when a context is active. **Every existing caller of `get_settings()` is untouched.**

- [ ] **Step 1: Write the failing test**

```python
# tests/tenancy/test_settings_overlay.py
from resume_agent.config import Settings, env_settings, get_settings
from resume_agent.tenancy.context import use_context

from tests.tenancy.test_context import make_ctx


def test_get_settings_prefers_active_context():
    user_settings = Settings(_env_file=None, anthropic_api_key="user-key")
    ctx = make_ctx(settings=user_settings)
    with use_context(ctx):
        assert get_settings() is user_settings
    assert get_settings() is env_settings()


def test_env_settings_is_cached_and_clearable():
    first = env_settings()
    assert env_settings() is first
    env_settings.cache_clear()
    assert env_settings() is not first
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/tenancy/test_settings_overlay.py -v`
Expected: FAIL — `ImportError: cannot import name 'env_settings'`

- [ ] **Step 3: Implement**

In `src/resume_agent/config.py`, replace the cached accessor (lines 51-54):

```python
@lru_cache
def env_settings() -> Settings:
    """Process-wide settings from .env — the no-context fallback (ADR-0003)."""
    return Settings()


def get_settings() -> Settings:
    """The active UserContext's effective settings, else env settings.

    Never cache the result across requests: the same call site serves
    different users (ADR-0003).
    """
    from resume_agent.tenancy.context import current_context

    ctx = current_context()
    if ctx is not None:
        return ctx.settings
    return env_settings()
```

Update the two `cache_clear` call sites (they cleared the old lru_cache on `get_settings`):

- `src/resume_agent/api/routers/admin.py:85`: `get_settings.cache_clear()` → `env_settings.cache_clear()` (add `env_settings` to the `from resume_agent.config import ...` line).
- `src/resume_agent/services/env_config.py:40`: same substitution.

- [ ] **Step 4: Run the full suite — this touches everything**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: all pass (no context is ever set yet, so every path takes the fallback). Also run `ruff check`.

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/config.py src/resume_agent/api/routers/admin.py src/resume_agent/services/env_config.py tests/tenancy/test_settings_overlay.py
git commit -m "Routes get_settings() through the active UserContext"
```

---

### Task 3: WorkspacePaths, provisioning, and the effective-Settings overlay

**Files:**

- Create: `src/resume_agent/tenancy/workspace.py`
- Test: `tests/tenancy/test_workspace.py`

**Interfaces:**

- Consumes: `Settings` from `resume_agent.config`.
- Produces:
  - `WorkspacePaths` (frozen dataclass over `root: Path`) with properties `db_file`, `db_url` (str, `sqlite:///` + posix path), `profile_dir`, `config_dir`, `secrets_env`, `output_dir`, `runs_root`.
  - `workspace_paths(data_root: Path, user_id: str) -> WorkspacePaths`
  - `provision_workspace(data_root: Path, user_id: str, *, template_dir: Path = Path("config")) -> WorkspacePaths`
  - `effective_settings(base: Settings, ws: WorkspacePaths) -> Settings`

- [ ] **Step 1: Write the failing tests**

```python
# tests/tenancy/test_workspace.py
from pathlib import Path

from resume_agent.config import Settings
from resume_agent.tenancy.workspace import (
    effective_settings,
    provision_workspace,
    workspace_paths,
)


def test_workspace_paths_shape(tmp_path):
    ws = workspace_paths(tmp_path, "abc123def456")
    assert ws.root == tmp_path / "users" / "abc123def456"
    assert ws.db_url == f"sqlite:///{(ws.root / 'resume_agent.db').as_posix()}"
    assert ws.config_dir == ws.root / "config"
    assert ws.secrets_env == ws.root / "secrets.env"


def test_provision_creates_dirs_and_copies_templates(tmp_path):
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    (template_dir / "search.yaml.example").write_text("titles: []\n", encoding="utf-8")
    ws = provision_workspace(tmp_path / "data", "abc123def456", template_dir=template_dir)
    assert ws.profile_dir.is_dir()
    assert ws.output_dir.is_dir()
    assert (ws.config_dir / "search.yaml").read_text(encoding="utf-8") == "titles: []\n"


def test_provision_never_overwrites_existing_config(tmp_path):
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    (template_dir / "search.yaml.example").write_text("template\n", encoding="utf-8")
    ws = provision_workspace(tmp_path / "data", "abc123def456", template_dir=template_dir)
    (ws.config_dir / "search.yaml").write_text("user-edited\n", encoding="utf-8")
    provision_workspace(tmp_path / "data", "abc123def456", template_dir=template_dir)
    assert (ws.config_dir / "search.yaml").read_text(encoding="utf-8") == "user-edited\n"


def test_effective_settings_overlays_user_secrets(tmp_path):
    ws = provision_workspace(tmp_path / "data", "abc123def456", template_dir=tmp_path)
    ws.secrets_env.write_text(
        "ANTHROPIC_API_KEY=user-key\nGITHUB_TOKEN=user-gh\n", encoding="utf-8"
    )
    base = Settings(_env_file=None, anthropic_api_key="server-key")
    eff = effective_settings(base, ws)
    assert eff.anthropic_api_key == "user-key"
    assert eff.github_token == "user-gh"
    assert eff.db_url == ws.db_url
    assert base.anthropic_api_key == "server-key"  # base untouched


def test_effective_settings_ignores_platform_fields(tmp_path):
    ws = provision_workspace(tmp_path / "data", "abc123def456", template_dir=tmp_path)
    ws.secrets_env.write_text(
        "SESSION_SECRET=evil\nAUTH_USERNAME=evil\nDB_URL=sqlite:///evil.db\n",
        encoding="utf-8",
    )
    base = Settings(_env_file=None, session_secret="server-secret")
    eff = effective_settings(base, ws)
    assert eff.session_secret == "server-secret"
    assert eff.auth_username == ""
    assert eff.db_url == ws.db_url


def test_effective_settings_without_secrets_file(tmp_path):
    ws = workspace_paths(tmp_path, "abc123def456")
    base = Settings(_env_file=None)
    eff = effective_settings(base, ws)
    assert eff.db_url == ws.db_url
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/tenancy/test_workspace.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement**

```python
# src/resume_agent/tenancy/workspace.py
"""Workspace layout, provisioning, and the effective-Settings overlay.

A Workspace is one user's tree under ``data/users/<user_id>/`` — the unit of
tenancy isolation (see CONTEXT.md). ``effective_settings`` overlays the
user's ``secrets.env`` (Operational secrets only — GitHub/Adzuna/own LLM
keys) onto the server settings; Platform secrets (session signing, auth
seed, db_url, api plumbing) can never be overridden from inside a workspace.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from resume_agent.config import Settings

#: config templates copied (as ``<name>``) from ``<template_dir>/<name>.example``
_TEMPLATE_CONFIGS = ("search.yaml", "connectors.yaml", "review.yaml", "prune.yaml")

#: fields a workspace secrets.env may override: str-typed, non-platform
_PLATFORM_FIELDS = frozenset(
    {"db_url", "api_token", "auth_username", "auth_password_hash", "session_secret", "cors_origins"}
)
_OVERLAY_FIELDS = frozenset(
    name
    for name, field in Settings.model_fields.items()
    if field.annotation is str and name not in _PLATFORM_FIELDS
)


@dataclass(frozen=True)
class WorkspacePaths:
    root: Path

    @property
    def db_file(self) -> Path:
        return self.root / "resume_agent.db"

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_file.as_posix()}"

    @property
    def profile_dir(self) -> Path:
        return self.root / "profile"

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def secrets_env(self) -> Path:
        return self.root / "secrets.env"

    @property
    def output_dir(self) -> Path:
        return self.root / "output"

    @property
    def runs_root(self) -> Path:
        return self.root / "runs"


def workspace_paths(data_root: Path | str, user_id: str) -> WorkspacePaths:
    return WorkspacePaths(root=Path(data_root) / "users" / user_id)


def provision_workspace(
    data_root: Path | str, user_id: str, *, template_dir: Path = Path("config")
) -> WorkspacePaths:
    """Create the workspace skeleton; copy config templates; never overwrite."""
    ws = workspace_paths(data_root, user_id)
    for directory in (ws.profile_dir, ws.config_dir, ws.output_dir, ws.runs_root):
        directory.mkdir(parents=True, exist_ok=True)
    for name in _TEMPLATE_CONFIGS:
        example = Path(template_dir) / f"{name}.example"
        target = ws.config_dir / name
        if example.is_file() and not target.exists():
            shutil.copyfile(example, target)
    return ws


def effective_settings(base: Settings, ws: WorkspacePaths) -> Settings:
    """Server settings + workspace overlay; always repoints db_url at the workspace."""
    update: dict[str, object] = {"db_url": ws.db_url}
    if ws.secrets_env.is_file():
        for key, value in dotenv_values(ws.secrets_env).items():
            field = key.lower()
            if field in _OVERLAY_FIELDS and value:
                update[field] = value
    return base.model_copy(update=update)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/tenancy/test_workspace.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tenancy/workspace.py tests/tenancy/test_workspace.py
git commit -m "Adds Workspace layout, provisioning, and effective-Settings overlay"
```

---

### Task 4: system.db — SystemBase, User table, engine helpers

**Files:**

- Create: `src/resume_agent/tenancy/system_db.py`
- Test: `tests/tenancy/test_system_db.py`

**Interfaces:**

- Consumes: `_enable_sqlite_write_concurrency` from `resume_agent.db` (reuse the WAL pragmas).
- Produces:
  - `SystemBase` (SQLAlchemy `DeclarativeBase` with **its own metadata** — deliberately not SQLModel).
  - `User` ORM model: `id: str` PK, `username: str` unique+indexed, `password_hash: str`, `role: str` default `"user"`, `disabled_at: datetime | None`, `weekly_token_budget: int | None`, `max_active_jobs: int | None`, `max_concurrent_runs: int | None`, `created_at`, `updated_at`.
  - `system_db_url(data_root: Path) -> str`, `make_system_engine(data_root: Path) -> Engine`, `init_system_db(engine) -> None`.
  - Plan 2 adds `InviteCode` / `ApiToken` / `UsageEvent` / `SystemSetting` to this module.

- [ ] **Step 1: Write the failing tests**

```python
# tests/tenancy/test_system_db.py
from pathlib import Path

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from resume_agent.db import init_db, make_engine
from resume_agent.tenancy.system_db import (
    User,
    init_system_db,
    make_system_engine,
    system_db_url,
)


def test_system_db_url(tmp_path):
    assert system_db_url(tmp_path) == f"sqlite:///{(tmp_path / 'system.db').as_posix()}"


def test_init_creates_users_table_and_is_idempotent(tmp_path):
    engine = make_system_engine(tmp_path)
    init_system_db(engine)
    init_system_db(engine)
    assert "users" in inspect(engine).get_table_names()
    engine.dispose()


def test_user_roundtrip(tmp_path):
    engine = make_system_engine(tmp_path)
    init_system_db(engine)
    with Session(engine) as session:
        session.add(User(id="abc123def456", username="alice", password_hash="pbkdf2:x", role="admin"))
        session.commit()
    with Session(engine) as session:
        row = session.execute(select(User).where(User.username == "alice")).scalar_one()
        assert row.role == "admin"
        assert row.disabled_at is None
        assert row.weekly_token_budget is None
    engine.dispose()


def test_metadata_isolation(tmp_path):
    """System tables never leak into workspace DBs and vice versa."""
    system_engine = make_system_engine(tmp_path)
    init_system_db(system_engine)
    assert "job" not in inspect(system_engine).get_table_names()

    ws_engine = make_engine(f"sqlite:///{(tmp_path / 'ws.db').as_posix()}")
    init_db(ws_engine)
    assert "users" not in inspect(ws_engine).get_table_names()
    system_engine.dispose()
    ws_engine.dispose()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/tenancy/test_system_db.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement**

```python
# src/resume_agent/tenancy/system_db.py
"""Shared system database: users (Plan 2 adds invites, tokens, usage, settings).

Deliberately plain SQLAlchemy with a private DeclarativeBase: SQLModel's
metadata is process-global, so defining these tables through SQLModel would
make every workspace ``init_db``/``create_all`` create system tables inside
workspace DBs (and workspace tables inside system.db). Separate metadata
makes the by-file isolation structural.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import DateTime, Integer, String, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from resume_agent.db import _enable_sqlite_write_concurrency


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SystemBase(DeclarativeBase):
    """Own metadata — system tables never mix with workspace (SQLModel) tables."""


class User(SystemBase):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False, default="user")
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # NULL = use the system default; 0 = unlimited (spec §4)
    weekly_token_budget: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_active_jobs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_concurrent_runs: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


def system_db_url(data_root: Path | str) -> str:
    return f"sqlite:///{(Path(data_root) / 'system.db').as_posix()}"


def make_system_engine(data_root: Path | str) -> Engine:
    Path(data_root).mkdir(parents=True, exist_ok=True)
    engine = create_engine(system_db_url(data_root), echo=False)
    _enable_sqlite_write_concurrency(engine)
    return engine


def init_system_db(engine: Engine) -> None:
    SystemBase.metadata.create_all(engine)
```

Note: check the actual workspace table name in `tracking/tables.py` for the isolation test (`inspect(...).get_table_names()`); SQLModel default-lowercases the class name, so `Job` → `job`. Adjust the assertion to whatever `init_db` actually creates if it differs.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/tenancy/test_system_db.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tenancy/system_db.py tests/tenancy/test_system_db.py
git commit -m "Adds system.db with isolated metadata and the User table"
```

---

### Task 5: EngineRegistry

**Files:**

- Create: `src/resume_agent/tenancy/engines.py`
- Test: `tests/tenancy/test_engines.py`

**Interfaces:**

- Consumes: `make_engine`, `init_db` from `resume_agent.db`.
- Produces: `EngineRegistry` with `get(user_id: str, db_url: str) -> Engine` (lazy create + `init_db` once, cached), `evict(user_id: str) -> None` (dispose + drop — the delete-user precondition), `close_all() -> None` (shutdown).

- [ ] **Step 1: Write the failing tests**

```python
# tests/tenancy/test_engines.py
from sqlalchemy import inspect

from resume_agent.tenancy.engines import EngineRegistry


def _url(tmp_path, name):
    return f"sqlite:///{(tmp_path / name).as_posix()}"


def test_get_creates_once_and_caches(tmp_path):
    registry = EngineRegistry()
    first = registry.get("u1", _url(tmp_path, "u1.db"))
    second = registry.get("u1", _url(tmp_path, "u1.db"))
    assert first is second
    assert "job" in inspect(first).get_table_names()  # init_db ran
    registry.close_all()


def test_distinct_users_get_distinct_engines(tmp_path):
    registry = EngineRegistry()
    a = registry.get("u1", _url(tmp_path, "u1.db"))
    b = registry.get("u2", _url(tmp_path, "u2.db"))
    assert a is not b
    registry.close_all()


def test_evict_disposes_and_recreates(tmp_path):
    registry = EngineRegistry()
    first = registry.get("u1", _url(tmp_path, "u1.db"))
    registry.evict("u1")
    second = registry.get("u1", _url(tmp_path, "u1.db"))
    assert first is not second
    registry.close_all()


def test_evict_unknown_is_noop():
    EngineRegistry().evict("ghost")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/tenancy/test_engines.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement**

```python
# src/resume_agent/tenancy/engines.py
"""Per-user workspace engine registry.

Engines are created lazily through the existing make_engine (WAL + busy
timeout carry over) and init_db (workspace migrations apply on first touch).
No eviction policy: a small group's engines are cheap. evict() exists for
user deletion — dispose before the workspace directory is removed, or open
SQLite handles block the removal on Windows.
"""

from __future__ import annotations

import threading

from sqlalchemy.engine import Engine

from resume_agent.db import init_db, make_engine


class EngineRegistry:
    def __init__(self) -> None:
        self._engines: dict[str, Engine] = {}
        self._lock = threading.Lock()

    def get(self, user_id: str, db_url: str) -> Engine:
        with self._lock:
            engine = self._engines.get(user_id)
            if engine is None:
                engine = make_engine(db_url)
                init_db(engine)
                self._engines[user_id] = engine
            return engine

    def evict(self, user_id: str) -> None:
        with self._lock:
            engine = self._engines.pop(user_id, None)
        if engine is not None:
            engine.dispose()

    def close_all(self) -> None:
        with self._lock:
            engines = list(self._engines.values())
            self._engines.clear()
        for engine in engines:
            engine.dispose()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/tenancy/test_engines.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tenancy/engines.py tests/tenancy/test_engines.py
git commit -m "Adds per-user workspace EngineRegistry"
```

---

### Task 6: Legacy-root adoption

**Files:**

- Create: `src/resume_agent/tenancy/migrate.py`
- Test: `tests/tenancy/test_migrate.py`

**Interfaces:**

- Produces: `is_legacy_root(data_root: Path) -> bool`, `adopt_legacy_root(data_root: Path, admin_id: str) -> list[str]` (returns moved child names), `AdoptionError(RuntimeError)`.
- Consumed by Task 7's bootstrap.

- [ ] **Step 1: Write the failing tests**

```python
# tests/tenancy/test_migrate.py
import pytest

from resume_agent.tenancy.migrate import AdoptionError, adopt_legacy_root, is_legacy_root


def _make_legacy_root(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    (root / "resume_agent.db").write_bytes(b"sqlite-bytes")
    (root / "profile").mkdir()
    (root / "profile" / "facts.json").write_text("{}", encoding="utf-8")
    (root / "output").mkdir()
    (root / ".env").write_text("GITHUB_TOKEN=tok\n", encoding="utf-8")
    return root


def test_is_legacy_root(tmp_path):
    root = _make_legacy_root(tmp_path)
    assert is_legacy_root(root)


def test_fresh_root_is_not_legacy(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    assert not is_legacy_root(root)
    (root / "system.db").write_bytes(b"")
    (root / "users").mkdir()
    assert not is_legacy_root(root)


def test_adopt_moves_children_into_workspace(tmp_path):
    root = _make_legacy_root(tmp_path)
    moved = adopt_legacy_root(root, "abc123def456")
    ws = root / "users" / "abc123def456"
    assert (ws / "resume_agent.db").read_bytes() == b"sqlite-bytes"
    assert (ws / "profile" / "facts.json").is_file()
    assert (ws / "secrets.env").read_text(encoding="utf-8") == "GITHUB_TOKEN=tok\n"
    assert not (root / "profile").exists()
    assert not (root / ".env").exists()
    assert set(moved) == {"resume_agent.db", "profile", "output", ".env"}
    assert not is_legacy_root(root)


def test_adopt_resumes_after_partial_move(tmp_path):
    """A half-completed adoption re-run moves the remainder."""
    root = _make_legacy_root(tmp_path)
    ws = root / "users" / "abc123def456"
    ws.mkdir(parents=True)
    (root / "resume_agent.db").rename(ws / "resume_agent.db")  # simulate crash after 1 move
    moved = adopt_legacy_root(root, "abc123def456")
    assert "resume_agent.db" not in moved
    assert (ws / "profile").is_dir()
    assert not is_legacy_root(root)


def test_adopt_refuses_to_overwrite(tmp_path):
    root = _make_legacy_root(tmp_path)
    ws = root / "users" / "abc123def456"
    ws.mkdir(parents=True)
    (ws / "profile").mkdir()
    (root / "profile" / "extra.txt").write_text("x", encoding="utf-8")
    with pytest.raises(AdoptionError):
        adopt_legacy_root(root, "abc123def456")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/tenancy/test_migrate.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement**

```python
# src/resume_agent/tenancy/migrate.py
"""One-time adoption of a legacy single-user data root into the first
admin's Workspace.

Child-swap semantics (the volume root itself cannot be renamed on Railway,
per the admin-import precedent): each legacy child is moved individually
into ``users/<admin_id>/``. A crash mid-way leaves already-moved children in
place; re-running moves the remainder — resumable, and a completed adoption
is a no-op because no legacy children remain at the root.
"""

from __future__ import annotations

import shutil
from pathlib import Path

#: everything a legacy root may contain, in move order (DB artifacts first so
#: a resumed adoption never sees a root DB without its WAL sidecars)
_LEGACY_CHILDREN = (
    "resume_agent.db",
    "resume_agent.db-wal",
    "resume_agent.db-shm",
    "profile",
    "config",
    "output",
    "runs",
    "progress",
    "scraper_recipes",
    "workday_facets",
    "taxonomy",
)


class AdoptionError(RuntimeError):
    """Adoption would overwrite existing workspace content — refuse loudly."""


def is_legacy_root(data_root: Path | str) -> bool:
    root = Path(data_root)
    if any((root / child).exists() for child in _LEGACY_CHILDREN):
        return True
    return (root / ".env").is_file()


def adopt_legacy_root(data_root: Path | str, admin_id: str) -> list[str]:
    root = Path(data_root)
    workspace = root / "users" / admin_id
    workspace.mkdir(parents=True, exist_ok=True)
    moved: list[str] = []
    for child in _LEGACY_CHILDREN:
        source = root / child
        if not source.exists():
            continue
        target = workspace / child
        if target.exists():
            raise AdoptionError(
                f"refusing to adopt: {target} already exists (would overwrite)"
            )
        shutil.move(str(source), str(target))
        moved.append(child)
    env_file = root / ".env"
    if env_file.is_file():
        secrets_target = workspace / "secrets.env"
        if secrets_target.exists():
            raise AdoptionError(f"refusing to adopt: {secrets_target} already exists")
        shutil.move(str(env_file), str(secrets_target))
        moved.append(".env")
    return moved
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/tenancy/test_migrate.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tenancy/migrate.py tests/tenancy/test_migrate.py
git commit -m "Adds resumable legacy-root adoption into the admin workspace"
```

---

### Task 7: Bootstrap — seed admin, adopt, build the default context

**Files:**

- Create: `src/resume_agent/tenancy/bootstrap.py`
- Test: `tests/tenancy/test_bootstrap.py`

**Interfaces:**

- Consumes: Tasks 3-6 (`workspace_paths`, `provision_workspace`, `effective_settings`, `User`, `init_system_db`, `make_system_engine`, `is_legacy_root`, `adopt_legacy_root`, `EngineRegistry`), `new_user_id` from Task 1, `hash-format` password hashes verbatim from `Settings.auth_password_hash`.
- Produces:
  - `BootstrapError(RuntimeError)`
  - `ensure_bootstrapped(data_root: Path, system_engine: Engine, settings: Settings) -> User` — seeds the first admin when `users` is empty (raising `BootstrapError` without env creds), adopts a legacy root, provisions the workspace skeleton; idempotent.
  - `build_context(user: User, data_root: Path, base_settings: Settings, registry: EngineRegistry) -> UserContext` — the one constructor for a server-side `UserContext`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/tenancy/test_bootstrap.py
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from resume_agent.config import Settings
from resume_agent.tenancy.bootstrap import (
    BootstrapError,
    build_context,
    ensure_bootstrapped,
)
from resume_agent.tenancy.engines import EngineRegistry
from resume_agent.tenancy.system_db import User, init_system_db, make_system_engine


def _settings(**overrides) -> Settings:
    values = dict(auth_username="owner", auth_password_hash="pbkdf2:120000:aa:bb")
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
def system_engine(tmp_path):
    engine = make_system_engine(tmp_path / "data")
    init_system_db(engine)
    yield engine
    engine.dispose()


def test_seeds_admin_when_empty(tmp_path, system_engine):
    admin = ensure_bootstrapped(tmp_path / "data", system_engine, _settings())
    assert admin.role == "admin"
    assert admin.username == "owner"
    with Session(system_engine) as session:
        assert session.execute(select(User)).scalars().one().id == admin.id


def test_refuses_without_seed_credentials(tmp_path, system_engine):
    with pytest.raises(BootstrapError):
        ensure_bootstrapped(
            tmp_path / "data", system_engine, _settings(auth_username="", auth_password_hash="")
        )


def test_idempotent_and_seed_only(tmp_path, system_engine):
    first = ensure_bootstrapped(tmp_path / "data", system_engine, _settings())
    # env rotation after seeding changes nothing (seed-only, spec §3)
    second = ensure_bootstrapped(
        tmp_path / "data", system_engine, _settings(auth_password_hash="pbkdf2:120000:cc:dd")
    )
    assert second.id == first.id
    assert second.password_hash == "pbkdf2:120000:aa:bb"


def test_adopts_legacy_root(tmp_path, system_engine):
    root = tmp_path / "data"
    (root / "profile").mkdir(parents=True)
    (root / "profile" / "facts.json").write_text("{}", encoding="utf-8")
    admin = ensure_bootstrapped(root, system_engine, _settings())
    assert (root / "users" / admin.id / "profile" / "facts.json").is_file()
    # re-boot is a no-op
    ensure_bootstrapped(root, system_engine, _settings())


def test_build_context(tmp_path, system_engine):
    root = tmp_path / "data"
    admin = ensure_bootstrapped(root, system_engine, _settings())
    registry = EngineRegistry()
    ctx = build_context(admin, root, _settings(), registry)
    assert ctx.user_id == admin.id
    assert ctx.is_admin
    assert ctx.workspace == root / "users" / admin.id
    assert ctx.settings.db_url.endswith(f"users/{admin.id}/resume_agent.db")
    assert ctx.engine is registry.get(admin.id, ctx.settings.db_url)
    registry.close_all()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/tenancy/test_bootstrap.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement**

```python
# src/resume_agent/tenancy/bootstrap.py
"""First-boot seeding and legacy adoption.

AUTH_USERNAME/AUTH_PASSWORD_HASH are seed-only: read exactly once, when the
users table is empty. Registration is invite-only, so an instance with no
admin would be permanently locked out — hence the hard refusal.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from resume_agent.config import Settings
from resume_agent.tenancy.context import UserContext, new_user_id
from resume_agent.tenancy.engines import EngineRegistry
from resume_agent.tenancy.migrate import adopt_legacy_root, is_legacy_root
from resume_agent.tenancy.system_db import User
from resume_agent.tenancy.workspace import (
    effective_settings,
    provision_workspace,
    workspace_paths,
)


class BootstrapError(RuntimeError):
    """The server must not start: no users and no seed credentials."""


def ensure_bootstrapped(
    data_root: Path | str, system_engine: Engine, settings: Settings
) -> User:
    """Seed the first admin, adopt a legacy root, provision the workspace.

    Idempotent: safe on every startup. Returns the first admin user.
    """
    data_root = Path(data_root)
    with Session(system_engine) as session:
        admin = session.execute(
            select(User).where(User.role == "admin").order_by(User.created_at)
        ).scalars().first()
        if admin is None:
            if not (settings.auth_username and settings.auth_password_hash):
                raise BootstrapError(
                    "users table is empty and AUTH_USERNAME/AUTH_PASSWORD_HASH are "
                    "unset — set both to seed the first admin (registration is "
                    "invite-only; without an admin the instance is locked out)"
                )
            admin = User(
                id=new_user_id(),
                username=settings.auth_username,
                password_hash=settings.auth_password_hash,
                role="admin",
            )
            session.add(admin)
            session.commit()
        session.refresh(admin)
        session.expunge(admin)
    if is_legacy_root(data_root):
        adopt_legacy_root(data_root, admin.id)
    provision_workspace(data_root, admin.id)
    return admin


def build_context(
    user: User,
    data_root: Path | str,
    base_settings: Settings,
    registry: EngineRegistry,
) -> UserContext:
    """The single server-side UserContext constructor."""
    ws = workspace_paths(data_root, user.id)
    settings = effective_settings(base_settings, ws)
    engine = registry.get(user.id, ws.db_url)
    return UserContext(
        user_id=user.id,
        username=user.username,
        role=user.role,
        workspace=ws.root,
        settings=settings,
        engine=engine,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/tenancy/test_bootstrap.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tenancy/bootstrap.py tests/tenancy/test_bootstrap.py
git commit -m "Adds seed-only bootstrap and the server UserContext constructor"
```

---

### Task 8: App wiring — multi-user boot, context dependency, run propagation

**Files:**

- Modify: `src/resume_agent/api/app.py` (lifespan, guarded dependencies)
- Modify: `src/resume_agent/api/deps.py` (`get_session`, new `get_user_context`)
- Modify: `src/resume_agent/api/runs/manager.py:220-236` (`submit` context capture)
- Test: `tests/api/test_multi_user_boot.py`, extend `tests/tenancy/test_context.py` coverage via a RunManager test in `tests/api/test_multi_user_boot.py`

**Interfaces:**

- Consumes: everything from Tasks 1-7.
- Produces:
  - `create_app` boots **multi-user** when the resolved DB is file-backed AND (`data_root/system.db` exists OR both `auth_username`/`auth_password_hash` are set). In-memory SQLite always boots legacy (test substrate). Multi-user boot: `app.state.system_engine`, `app.state.engine_registry`, `app.state.default_context` (the sole admin's `UserContext` — transitional identity until Plan 2's per-user auth), and `app.state.engine` pointing at the admin workspace engine so unconverted `app.state.engine` call sites (`runs.py:51`, `match_gap.py:71`, `suggestions.py:97,150`, `admin.py`) keep working against the right DB. Legacy boot: exactly today's behavior with `system_engine`/`engine_registry`/`default_context` set to `None`.
  - `get_user_context(request) -> Iterator[UserContext | None]` dependency (yields inside `use_context` when multi-user; yields `None` in legacy mode). Appended to the guarded dependency list **after** `require_token`.
  - `RunManager.submit` runs workers inside `contextvars.copy_context()` captured at submit time — the run-worker set-point of ADR-0003.

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_multi_user_boot.py
"""Multi-user boot path: system.db, bootstrap, default context, run propagation."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.api.runs.manager import RunManager
from resume_agent.tenancy.context import current_context, use_context

from tests.tenancy.test_context import make_ctx


def _write_env(tmp_path: Path) -> Path:
    env = tmp_path / ".env"
    env.write_text(
        "AUTH_USERNAME=owner\n"
        "AUTH_PASSWORD_HASH=pbkdf2:120000:aa:bb\n"
        "SESSION_SECRET=test-secret\n"
        "API_TOKEN=test-token\n",
        encoding="utf-8",
    )
    return env


def _make_app(tmp_path: Path):
    data_dir = tmp_path / "data"
    return create_app(
        db_url=f"sqlite:///{(data_dir / 'ignored.db').as_posix()}",
        env_path=_write_env(tmp_path),
        data_dir=data_dir,
        runs_root=tmp_path / "runs",
        config_dir=tmp_path / "config",
    )


def test_multi_user_boot_creates_system_db_and_admin_workspace(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app):
        assert (tmp_path / "data" / "system.db").is_file()
        ctx = app.state.default_context
        assert ctx is not None and ctx.role == "admin"
        assert (tmp_path / "data" / "users" / ctx.user_id).is_dir()
        assert app.state.engine is ctx.engine


def test_legacy_boot_for_memory_sqlite():
    app = create_app(db_url="sqlite://", api_token="")
    with TestClient(app) as client:
        assert app.state.system_engine is None
        assert app.state.default_context is None
        assert client.get("/api/health").status_code == 200


def test_guarded_route_runs_inside_default_context(tmp_path):
    app = _make_app(tmp_path)
    with TestClient(app) as client:
        response = client.get(
            "/api/jobs", headers={"Authorization": "Bearer test-token"}
        )
        assert response.status_code == 200  # served from the admin workspace DB


def test_run_manager_propagates_context(tmp_path):
    manager = RunManager(root=tmp_path / "runs", executor=ThreadPoolExecutor(max_workers=1))
    ctx = make_ctx(username="runner")
    seen = []

    def worker(reporter):
        seen.append(current_context())
        return {}

    with use_context(ctx):
        run_id = manager.submit("pull", worker)
    for _ in range(100):
        snapshot = manager.get(run_id)
        if snapshot is not None and snapshot.state not in ("pending", "running"):
            break
    manager.shutdown()
    assert seen == [ctx]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_multi_user_boot.py -v`
Expected: FAIL — `app.state` has no `system_engine` / `default_context`; run worker sees `None`.

- [ ] **Step 3: Implement the RunManager propagation**

In `src/resume_agent/api/runs/manager.py`, add `import contextvars` to the imports, then in `submit` change the executor call (currently `future = executor.submit(_runner)`):

```python
            # ADR-0003: the worker runs in the submitting caller's context so
            # tenancy (settings, usage identity) survives the thread hop.
            submission_context = contextvars.copy_context()
            executor = self._kind_executors.get(kind, self.executor)
            try:
                future = executor.submit(submission_context.run, _runner)
```

- [ ] **Step 4: Implement `get_user_context` and context-aware `get_session` in `deps.py`**

```python
# add to src/resume_agent/api/deps.py
from resume_agent.tenancy.context import UserContext, current_context, use_context


def get_user_context(request: Request) -> Iterator[UserContext | None]:
    """Activate the request's UserContext (ADR-0003 request set-point).

    Transitional (Plan 1): multi-user apps resolve every authenticated request
    to the sole admin's default context; Plan 2 replaces this with real
    per-user session/PAT resolution. Legacy apps yield None (env fallback).
    """
    ctx = getattr(request.app.state, "default_context", None)
    if ctx is None:
        yield None
        return
    with use_context(ctx):
        yield ctx
```

And change `get_session` to prefer the active context:

```python
def get_session(request: Request) -> Iterator[Session]:
    """Yield a session bound to the active context's engine (or the app engine)."""
    ctx = current_context()
    engine = ctx.engine if ctx is not None and ctx.engine is not None else request.app.state.engine
    with Session(engine) as session:
        yield session
```

- [ ] **Step 5: Implement the lifespan split in `app.py`**

Add imports:

```python
from resume_agent.api.deps import get_settings_dep, get_user_context, require_token
from resume_agent.tenancy.bootstrap import build_context, ensure_bootstrapped
from resume_agent.tenancy.engines import EngineRegistry
from resume_agent.tenancy.system_db import init_system_db, make_system_engine
```

Add the boot-mode predicate next to `spa_dist_dir`:

```python
def _multi_user_boot(data_dir: Path, db_url: str, settings: Settings) -> bool:
    """Multi-user when file-backed AND (already adopted OR seedable).

    In-memory SQLite is the offline-test substrate and always boots the
    legacy single-tenant path; Plan 2's auth tests opt in with a temp data
    root + seed credentials.
    """
    if db_url in {"sqlite://", "sqlite://:memory:", "sqlite:///:memory:"}:
        return False
    if (data_dir / "system.db").is_file():
        return True
    return bool(settings.auth_username and settings.auth_password_hash)
```

Replace the lifespan body:

```python
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        data_dir = app.state.data_dir
        if _multi_user_boot(data_dir, resolved_db, app.state.settings):
            system_engine = make_system_engine(data_dir)
            init_system_db(system_engine)
            admin = ensure_bootstrapped(data_dir, system_engine, app.state.settings)
            registry = EngineRegistry()
            ctx = build_context(admin, data_dir, app.state.settings, registry)
            app.state.system_engine = system_engine
            app.state.engine_registry = registry
            app.state.default_context = ctx
            app.state.engine = ctx.engine
        else:
            engine = make_engine(resolved_db)
            init_db(engine)
            app.state.system_engine = None
            app.state.engine_registry = None
            app.state.default_context = None
            app.state.engine = engine
        app.state.run_manager.recover_interrupted()
        app.state.run_manager.sweep()
        yield
        registry = app.state.engine_registry
        if registry is not None:
            registry.close_all()
        system_engine = app.state.system_engine
        if system_engine is not None:
            system_engine.dispose()
        app.state.run_manager.shutdown()
```

And extend the guarded dependency list:

```python
    guarded = [Depends(require_token), Depends(get_user_context)]
```

- [ ] **Step 6: Run the new tests, then the full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_multi_user_boot.py -v`
Expected: 4 passed

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check`
Expected: full suite green (every existing API test uses in-memory SQLite or no creds → legacy path). If any existing test uses a file-backed DB **with** creds, it now boots multi-user — fix that test by asserting against the new layout, not by weakening the gate.

- [ ] **Step 7: Commit**

```bash
git add src/resume_agent/api/app.py src/resume_agent/api/deps.py src/resume_agent/api/runs/manager.py tests/api/test_multi_user_boot.py
git commit -m "Boots multi-user apps through UserContext with run propagation"
```

---

### Task 9: CLI workspace resolution + docs

**Files:**

- Create: `src/resume_agent/tenancy/local.py`
- Modify: `src/resume_agent/cli.py` (root `@app.callback()`)
- Modify: `CLAUDE.md` (tenancy section)
- Test: `tests/tenancy/test_local.py`

**Interfaces:**

- Consumes: Tasks 1-7.
- Produces: `resolve_local_context(data_root: Path, username: str | None) -> UserContext | None` — `None` on a legacy root (env fallback = today's behavior); on a multi-user root builds the named user's (or sole first admin's) context. `activate_local_context(...)` wraps it with `activate()`. CLI gains a global `--user` option.

- [ ] **Step 1: Write the failing tests**

```python
# tests/tenancy/test_local.py
import pytest
from sqlalchemy.orm import Session

from resume_agent.tenancy.local import resolve_local_context
from resume_agent.tenancy.system_db import User, init_system_db, make_system_engine


def _seed(tmp_path, *users):
    root = tmp_path / "data"
    engine = make_system_engine(root)
    init_system_db(engine)
    with Session(engine) as session:
        for i, (name, role) in enumerate(users):
            session.add(User(id=f"{i:012x}", username=name, password_hash="h", role=role))
        session.commit()
    engine.dispose()
    return root


def test_legacy_root_returns_none(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    assert resolve_local_context(root, None) is None


def test_legacy_root_with_user_flag_raises(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    with pytest.raises(RuntimeError):
        resolve_local_context(root, "alice")


def test_defaults_to_first_admin(tmp_path):
    root = _seed(tmp_path, ("owner", "admin"), ("alice", "user"))
    ctx = resolve_local_context(root, None)
    assert ctx is not None and ctx.username == "owner"
    assert ctx.workspace == root / "users" / ctx.user_id
    ctx.engine.dispose()


def test_selects_named_user(tmp_path):
    root = _seed(tmp_path, ("owner", "admin"), ("alice", "user"))
    ctx = resolve_local_context(root, "alice")
    assert ctx is not None and ctx.username == "alice" and ctx.role == "user"
    ctx.engine.dispose()


def test_unknown_user_raises(tmp_path):
    root = _seed(tmp_path, ("owner", "admin"))
    with pytest.raises(RuntimeError):
        resolve_local_context(root, "ghost")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/tenancy/test_local.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement**

```python
# src/resume_agent/tenancy/local.py
"""CLI-side context resolution (the third ADR-0003 set-point).

Operator affordance only: the domain CLI works on a local data root
(legacy-shaped → env fallback, exactly today's behavior; multi-user →
default to the sole/first admin, --user to pick another). Remote group
members are web-UI-only.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from resume_agent.config import env_settings
from resume_agent.db import init_db, make_engine
from resume_agent.tenancy.context import UserContext, activate
from resume_agent.tenancy.system_db import User, init_system_db, make_system_engine
from resume_agent.tenancy.workspace import effective_settings, workspace_paths


def resolve_local_context(
    data_root: Path | str, username: str | None
) -> UserContext | None:
    root = Path(data_root)
    if not (root / "system.db").is_file():
        if username:
            raise RuntimeError(
                f"--user given but {root} is not a multi-user data root"
            )
        return None
    system_engine = make_system_engine(root)
    init_system_db(system_engine)
    try:
        with Session(system_engine) as session:
            if username:
                user = session.execute(
                    select(User).where(User.username == username)
                ).scalars().first()
                if user is None:
                    raise RuntimeError(f"no user named {username!r} in {root}")
            else:
                user = session.execute(
                    select(User).order_by(User.role != "admin", User.created_at)
                ).scalars().first()
                if user is None:
                    raise RuntimeError(f"{root} has a system.db but no users")
            session.expunge(user)
    finally:
        system_engine.dispose()
    ws = workspace_paths(root, user.id)
    engine = make_engine(ws.db_url)
    init_db(engine)
    return UserContext(
        user_id=user.id,
        username=user.username,
        role=user.role,
        workspace=ws.root,
        settings=effective_settings(env_settings(), ws),
        engine=engine,
    )


def activate_local_context(data_root: Path | str, username: str | None) -> UserContext | None:
    ctx = resolve_local_context(data_root, username)
    if ctx is not None:
        activate(ctx)
    return ctx
```

- [ ] **Step 4: Wire the CLI**

In `src/resume_agent/cli.py`, directly under `app = typer.Typer(...)` (line 41), add:

```python
@app.callback()
def _main(
    user: str | None = typer.Option(
        None,
        "--user",
        help="Workspace username on a multi-user data root (default: first admin).",
    ),
) -> None:
    from resume_agent.tenancy.local import activate_local_context

    activate_local_context(Path("data"), user)
```

Every existing command keeps working: on a legacy root nothing activates (env fallback); on a multi-user root, `get_settings().db_url` now points at the workspace DB so the `_engine(db_url)` helper and every service resolve per-workspace automatically.

- [ ] **Step 5: Run all tests + lint**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check`
Expected: green (CLI tests, if any invoke the typer app, hit the legacy path in the test cwd).

- [ ] **Step 6: Document in CLAUDE.md**

Append to `CLAUDE.md` under "Core invariants" a new subsection:

```markdown
### Tenancy context (ADR-0003)

Multi-user state rides a `contextvars.ContextVar` holding the active
`UserContext` (`tenancy/context.py`). Exactly three set-points: the API
dependency `get_user_context`, `RunManager.submit` (copies the caller's
context into the worker), and the CLI callback (`--user`). `get_settings()`
returns the context's effective settings, else env settings — never cache
its result across requests. With no context, behavior is the legacy
single-user path (tests, legacy roots). System tables (`tenancy/system_db.py`)
use their own SQLAlchemy metadata so they never leak into workspace DBs.
```

- [ ] **Step 7: Commit**

```bash
git add src/resume_agent/tenancy/local.py src/resume_agent/cli.py tests/tenancy/test_local.py CLAUDE.md
git commit -m "Resolves CLI workspace context on multi-user data roots"
```markdown
### Tenancy context (ADR-0003)

Multi-user state rides a `contextvars.ContextVar` holding the active
`UserContext` (`tenancy/context.py`). Exactly three set-points: the API
dependency `get_user_context`, `RunManager.submit` (copies the caller's
context into the worker), and the CLI callback (`--user`). `get_settings()`
returns the context's effective settings, else env settings — never cache
its result across requests. With no context, behavior is the legacy
single-user path (tests, legacy roots). System tables (`tenancy/system_db.py`)
use their own SQLAlchemy metadata so they never leak into workspace DBs.
```

- [ ] **Step 7: Commit**

```bash
git add src/resume_agent/tenancy/local.py src/resume_agent/cli.py tests/tenancy/test_local.py CLAUDE.md
git commit -m "Resolves CLI workspace context on multi-user data roots"
```
