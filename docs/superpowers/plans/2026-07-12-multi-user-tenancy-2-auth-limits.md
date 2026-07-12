# Multi-User Tenancy — Plan 2: Auth + Limits

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Real per-user authentication (register with invite codes, user-scoped sessions, PATs, link tokens, rate limiting) plus usage recording, token budgets, and resource quotas — replacing Plan 1's transitional "default context = sole admin".

**Architecture:** All credentials live in `system.db` (Plan 1's `SystemBase`). Sessions stay stateless: the HMAC signature mixes in a fragment of the user's password hash, so a password change invalidates sessions without a session table. Request auth resolves session cookie → PAT bearer → link-token query param, then builds the `UserContext` via Plan 1's `build_context`. Usage is recorded at `llm_runner.acall`; budgets are enforced per phase at service entrypoints; quotas at `RunManager.submit` and the ingest loop. Spec: `docs/superpowers/specs/2026-07-12-multi-user-tenancy-design.md`.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy ORM (system DB), pytest offline, existing pbkdf2 helpers in `api/auth.py`.

## Correctness amendments (audit before implementation)

These corrections are normative and override later reference snippets:

- Use Python **3.13+** and validate usernames, passwords, PAT names, invite
  parameters, and non-negative limits with typed boundary schemas. New PBKDF2
  hashes use the strengthened iteration policy while old hashes remain
  verifiable and are upgraded after successful authentication.
- Session signatures mix the complete password hash. Cookie `Secure` follows
  the effective HTTPS scheme (including trusted proxy scheme) so the documented
  localhost HTTP admin CLI can exchange login for a PAT.
- Registration records every failed outcome in the limiter, catches concurrent
  username uniqueness conflicts as `USERNAME_TAKEN`, atomically consumes only
  a still-valid/non-revoked invite, and remains recoverable if Workspace
  provisioning is interrupted (`build_context` self-heals provisioning).
- General request auth is **session -> header PAT only**. Remove query-token
  handling from `get_user_context`. Add a separate purpose-bound link
  dependency only to SSE/download routes; verify purpose, user status, and
  resource ownership. Replace the draft test that lets an `sse` token call
  `/api/jobs` with tests proving that request is rejected.
- Resolve all tenant resources through Plan 1 adapters. Isolation tests cover
  config, secrets, profile documents/files, setup status, suggestions/match-gap,
  jobs, and every run action, not only `GET /api/jobs`.
- Record usage after successful returns from both `AgentRunner.run` and
  `AgentRunner.arun`; `acall` is not the common seam. Use
  `ctx.system_engine` and `ctx.own_key_providers`, not a module-global engine or
  cwd `env_settings()` comparison. Add multi-app isolation and failed-write
  tests.
- Budget failures persist `errorCode=BUDGET_EXCEEDED`; quota failures persist
  or return `QUOTA_EXCEEDED` as appropriate. Budget guards cover every public
  phase that can reach an LLM, including synchronous suggestion/profile/
  extraction paths, without double-charging calls.
- Per-user run ownership applies to list/get/SSE/cancel/recovery, singleton
  keys are namespaced by user, and files live in the Workspace `runs/` root.
  Foreign ids return 404.
- Job-cap tests cover archived rows and the promised "upgrades still apply"
  behavior. The same-user pull singleton prevents two pull batches from racing
  the cap.
- Regenerate contracts only after all Plan 2 endpoints and typed error fields
  are complete. On Windows use the repository's direct Python +
  `openapi-typescript` fallback if the CRLF-sensitive bash wrapper fails.

## Global Constraints

- **Strict TDD** (superpowers:test-driven-development): every task writes its failing test first and runs it to observe RED before any implementation code; implementation is the minimum to reach GREEN. Never reorder these steps.
- Prerequisite: Plan 1 (`2026-07-12-multi-user-tenancy-1-core.md`) is fully landed.
- Secrets are never stored raw: invite codes and PATs store `sha256(secret)` hex; the raw value is shown exactly once. Prefixes: invites `inv_`, PATs `rat_`.
- Invite codes are role-less (always mint `role=user`), default expiry 14 days.
- Session cookie: `HttpOnly`, `SameSite=Lax`, `Secure` (already the repo's cookie shape).
- PATs are role-equivalent and **header-only**; link tokens are **query-only** (~10 min TTL). The static `api_token` is retired for multi-user apps (legacy in-memory test apps keep it as scaffolding only).
- Shipped defaults: `weekly_token_budget=10_000_000` weighted tokens, `max_active_jobs=2000`, `max_concurrent_runs=2`. `NULL` = use default, `0` = unlimited.
- Budget enforcement: rolling 7 days, per phase (never inside the semaphore-guarded leaf); admins and own-key usage recorded but never enforced. Failed usage writes must never fail the LLM call.
- Rate limiting: 10 failed login/register attempts per (username, client IP) per 15 minutes → 429 `RATE_LIMITED`; success resets; in-memory.
- Error codes (spec §7): `INVITE_INVALID`, `INVITE_USED`, `INVITE_EXPIRED`, `USERNAME_TAKEN`, `BUDGET_EXCEEDED`, `QUOTA_EXCEEDED` (429), `FORBIDDEN` (403), `USER_DISABLED`, `RATE_LIMITED` (429).
- Test: `.venv/Scripts/python.exe -m pytest`; lint: `ruff check`. Contract regen: `bash scripts/gen_ts_client.sh`; drift gate `tests/api/test_openapi_contract.py`.

---

### Task 1: System tables — InviteCode, ApiToken, UsageEvent, SystemSetting + secret helpers

**Files:**
- Modify: `src/resume_agent/tenancy/system_db.py` (append models)
- Create: `src/resume_agent/tenancy/secrets.py`
- Test: `tests/tenancy/test_system_tables.py`

**Interfaces:**
- Produces (models, all on `SystemBase`):
  - `InviteCode`: `id: str` PK, `code_hash: str` unique, `created_by: str`, `created_at`, `expires_at: datetime`, `used_by: str | None`, `used_at: datetime | None`, `revoked_at: datetime | None`.
  - `ApiToken`: `id: str` PK, `user_id: str` indexed, `name: str`, `token_hash: str` unique, `created_at`, `last_used_at: datetime | None`, `revoked_at: datetime | None`.
  - `UsageEvent`: `id: int` autoincrement PK, `user_id: str` indexed, `ts: datetime` (indexed with user_id), `provider: str | None`, `model: str | None`, `input_tokens: int`, `output_tokens: int`, `cache_read_tokens: int`, `cache_creation_tokens: int`, `weighted_total: float`, `own_key: bool` (Integer 0/1).
  - `SystemSetting`: `key: str` PK, `value: str`, `updated_at`.
- Produces (helpers): `mint_secret(prefix: str) -> str` (`prefix` + `secrets.token_urlsafe(32)`), `hash_secret(raw: str) -> str` (sha256 hexdigest).

- [ ] **Step 1: Write the failing tests**

```python
# tests/tenancy/test_system_tables.py
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from resume_agent.tenancy.secrets import hash_secret, mint_secret
from resume_agent.tenancy.system_db import (
    ApiToken,
    InviteCode,
    SystemSetting,
    UsageEvent,
    init_system_db,
    make_system_engine,
)


def test_mint_secret_shape():
    raw = mint_secret("inv_")
    assert raw.startswith("inv_")
    assert len(raw) > 30
    assert mint_secret("inv_") != raw


def test_hash_secret_is_stable_sha256():
    assert hash_secret("abc") == hash_secret("abc")
    assert len(hash_secret("abc")) == 64


def test_tables_roundtrip(tmp_path):
    engine = make_system_engine(tmp_path)
    init_system_db(engine)
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        session.add(InviteCode(
            id="i1", code_hash=hash_secret("inv_x"), created_by="admin1",
            expires_at=now + timedelta(days=14),
        ))
        session.add(ApiToken(id="t1", user_id="u1", name="cli", token_hash=hash_secret("rat_x")))
        session.add(UsageEvent(
            user_id="u1", ts=now, provider="anthropic", model="claude-sonnet-5",
            input_tokens=100, output_tokens=50, cache_read_tokens=0,
            cache_creation_tokens=0, weighted_total=250.0, own_key=False,
        ))
        session.add(SystemSetting(key="weekly_token_budget", value="10000000"))
        session.commit()
    with Session(engine) as session:
        assert session.execute(select(InviteCode)).scalars().one().used_at is None
        assert session.execute(select(ApiToken)).scalars().one().revoked_at is None
        assert session.execute(select(UsageEvent)).scalars().one().weighted_total == 250.0
        assert session.get(SystemSetting, "weekly_token_budget").value == "10000000"
    engine.dispose()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/tenancy/test_system_tables.py -v`
Expected: FAIL — imports missing

- [ ] **Step 3: Implement**

Append to `src/resume_agent/tenancy/system_db.py` (below `User`, reusing `utc_now`; add `Boolean, Float, Index` to the sqlalchemy import):

```python
class InviteCode(SystemBase):
    """Single-use, expiring, role-less registration secret (stored hashed)."""

    __tablename__ = "invite_codes"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    code_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_by: Mapped[str | None] = mapped_column(String, nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApiToken(SystemBase):
    """Role-equivalent personal access token; raw value shown once, stored hashed."""

    __tablename__ = "api_tokens"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    token_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UsageEvent(SystemBase):
    """Append-only per-LLM-call usage log. Recorded always; own_key rows and
    admin users are exempt from enforcement, never from recording."""

    __tablename__ = "usage_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_creation_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    weighted_total: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    own_key: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (Index("ix_usage_events_user_ts", "user_id", "ts"),)


class SystemSetting(SystemBase):
    """Admin-editable system defaults (budgets/quotas), stringly stored."""

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
```

```python
# src/resume_agent/tenancy/secrets.py
"""Mint-and-hash helpers shared by invite codes and PATs.

The raw secret is shown exactly once at mint time; only sha256(raw) is
persisted, so a system.db leak does not leak usable credentials.
"""

from __future__ import annotations

import hashlib
import secrets


def mint_secret(prefix: str) -> str:
    return f"{prefix}{secrets.token_urlsafe(32)}"


def hash_secret(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/tenancy/test_system_tables.py tests/tenancy/test_system_db.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tenancy/system_db.py src/resume_agent/tenancy/secrets.py tests/tenancy/test_system_tables.py
git commit -m "Adds invite/token/usage/setting system tables and secret helpers"
```

---

### Task 2: User-scoped sessions and link tokens (pure crypto in `api/auth.py`)

**Files:**
- Modify: `src/resume_agent/api/auth.py` (add user-scoped functions; keep the legacy single-account functions — legacy apps still use them until Task 5 rewires, and `hash_password`/`verify_password` are reused everywhere)
- Test: `tests/api/test_user_sessions.py`

**Interfaces:**
- Produces:
  - `issue_user_session(settings, *, user_id: str, password_hash: str, now: float | None = None) -> str` — token `"{user_id}:{expiry}:{sig}"`; `sig = HMAC-SHA256(key=f"{session_secret}:{password_hash[-16:]}", payload=f"{user_id}:{expiry}")`.
  - `parse_session_user_id(token: str) -> str | None` — unverified peek so the caller can load the user row.
  - `verify_user_session(token, settings, *, password_hash: str, now: float | None = None) -> str | None` — returns `user_id` or `None`.
  - `LINK_TOKEN_TTL_SECONDS = 600`; `issue_link_token(settings, *, user_id: str, purpose: str, now: float | None = None) -> str` (`"{user_id}:{purpose}:{expiry}:{sig}"`, HMAC with `session_secret` alone); `verify_link_token(token, settings, *, now: float | None = None) -> tuple[str, str] | None` returning `(user_id, purpose)`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_user_sessions.py
from resume_agent.api.auth import (
    LINK_TOKEN_TTL_SECONDS,
    SESSION_LIFETIME_SECONDS,
    issue_link_token,
    issue_user_session,
    parse_session_user_id,
    verify_link_token,
    verify_user_session,
)
from resume_agent.config import Settings

SETTINGS = Settings(_env_file=None, session_secret="s3cret")
HASH = "pbkdf2:120000:aa:bbccddeeff00112233"


def test_session_roundtrip():
    token = issue_user_session(SETTINGS, user_id="u1", password_hash=HASH, now=1000.0)
    assert parse_session_user_id(token) == "u1"
    assert verify_user_session(token, SETTINGS, password_hash=HASH, now=1000.0) == "u1"


def test_session_expires():
    token = issue_user_session(SETTINGS, user_id="u1", password_hash=HASH, now=1000.0)
    late = 1000.0 + SESSION_LIFETIME_SECONDS + 1
    assert verify_user_session(token, SETTINGS, password_hash=HASH, now=late) is None


def test_password_change_invalidates_session():
    token = issue_user_session(SETTINGS, user_id="u1", password_hash=HASH, now=1000.0)
    rotated = "pbkdf2:120000:aa:0000000000000000"
    assert verify_user_session(token, SETTINGS, password_hash=rotated, now=1000.0) is None


def test_tampered_user_id_rejected():
    token = issue_user_session(SETTINGS, user_id="u1", password_hash=HASH, now=1000.0)
    _, expiry, sig = token.split(":")
    assert verify_user_session(f"u2:{expiry}:{sig}", SETTINGS, password_hash=HASH, now=1000.0) is None


def test_link_token_roundtrip_and_expiry():
    token = issue_link_token(SETTINGS, user_id="u1", purpose="sse", now=1000.0)
    assert verify_link_token(token, SETTINGS, now=1000.0) == ("u1", "sse")
    assert verify_link_token(token, SETTINGS, now=1000.0 + LINK_TOKEN_TTL_SECONDS + 1) is None


def test_link_token_purpose_tamper_rejected():
    token = issue_link_token(SETTINGS, user_id="u1", purpose="sse", now=1000.0)
    user_id, purpose, expiry, sig = token.split(":")
    assert verify_link_token(f"{user_id}:download:{expiry}:{sig}", SETTINGS, now=1000.0) is None


def test_garbage_tokens_return_none():
    assert parse_session_user_id("not-a-token") is None
    assert verify_user_session("", SETTINGS, password_hash=HASH) is None
    assert verify_link_token("a:b", SETTINGS) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_user_sessions.py -v`
Expected: FAIL — imports missing

- [ ] **Step 3: Implement**

Append to `src/resume_agent/api/auth.py`:

```python
LINK_TOKEN_TTL_SECONDS = 600


def _sign_user(settings: Settings, payload: str, password_hash: str) -> str:
    # Mixing a hash fragment into the key means a password change (or admin
    # reset) invalidates that user's sessions with no session table.
    key = f"{settings.session_secret}:{password_hash[-16:]}"
    return hmac.new(key.encode(), payload.encode(), hashlib.sha256).hexdigest()


def issue_user_session(
    settings: Settings, *, user_id: str, password_hash: str, now: float | None = None
) -> str:
    issued_at = time.time() if now is None else now
    expiry = int(issued_at + SESSION_LIFETIME_SECONDS)
    payload = f"{user_id}:{expiry}"
    return f"{payload}:{_sign_user(settings, payload, password_hash)}"


def parse_session_user_id(token: str) -> str | None:
    """Unverified peek so the caller can load the user row to verify against."""
    try:
        user_id, _expiry, _sig = token.split(":")
    except (AttributeError, ValueError):
        return None
    return user_id or None


def verify_user_session(
    token: str, settings: Settings, *, password_hash: str, now: float | None = None
) -> str | None:
    if not settings.session_secret:
        return None
    try:
        user_id, expiry_text, signature = token.split(":")
        expiry = int(expiry_text)
    except (AttributeError, TypeError, ValueError):
        return None
    payload = f"{user_id}:{expiry}"
    if not hmac.compare_digest(signature, _sign_user(settings, payload, password_hash)):
        return None
    if (time.time() if now is None else now) >= expiry:
        return None
    return user_id


def _sign_link(settings: Settings, payload: str) -> str:
    return hmac.new(
        f"link:{settings.session_secret}".encode(), payload.encode(), hashlib.sha256
    ).hexdigest()


def issue_link_token(
    settings: Settings, *, user_id: str, purpose: str, now: float | None = None
) -> str:
    issued_at = time.time() if now is None else now
    expiry = int(issued_at + LINK_TOKEN_TTL_SECONDS)
    payload = f"{user_id}:{purpose}:{expiry}"
    return f"{payload}:{_sign_link(settings, payload)}"


def verify_link_token(
    token: str, settings: Settings, *, now: float | None = None
) -> tuple[str, str] | None:
    if not settings.session_secret:
        return None
    try:
        user_id, purpose, expiry_text, signature = token.split(":")
        expiry = int(expiry_text)
    except (AttributeError, TypeError, ValueError):
        return None
    payload = f"{user_id}:{purpose}:{expiry}"
    if not hmac.compare_digest(signature, _sign_link(settings, payload)):
        return None
    if (time.time() if now is None else now) >= expiry:
        return None
    return user_id, purpose
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_user_sessions.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/api/auth.py tests/api/test_user_sessions.py
git commit -m "Adds user-scoped stateless sessions and signed link tokens"
```

---

### Task 3: Failed-attempt rate limiter

**Files:**
- Create: `src/resume_agent/api/rate_limit.py`
- Test: `tests/api/test_rate_limit.py`

**Interfaces:**
- Produces: `FailedAttemptLimiter(max_failures: int = 10, window_seconds: float = 900.0)` with `blocked(username: str, ip: str, *, now: float | None = None) -> bool`, `record_failure(username, ip, *, now=None) -> None`, `reset(username, ip) -> None`. Instantiated once on `app.state.login_limiter` (Task 4).

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_rate_limit.py
from resume_agent.api.rate_limit import FailedAttemptLimiter


def test_blocks_after_max_failures():
    limiter = FailedAttemptLimiter(max_failures=3, window_seconds=900)
    for _ in range(3):
        assert not limiter.blocked("alice", "1.2.3.4", now=100.0)
        limiter.record_failure("alice", "1.2.3.4", now=100.0)
    assert limiter.blocked("alice", "1.2.3.4", now=100.0)


def test_window_rolls():
    limiter = FailedAttemptLimiter(max_failures=1, window_seconds=900)
    limiter.record_failure("alice", "1.2.3.4", now=100.0)
    assert limiter.blocked("alice", "1.2.3.4", now=200.0)
    assert not limiter.blocked("alice", "1.2.3.4", now=100.0 + 901.0)


def test_success_resets():
    limiter = FailedAttemptLimiter(max_failures=1, window_seconds=900)
    limiter.record_failure("alice", "1.2.3.4", now=100.0)
    limiter.reset("alice", "1.2.3.4")
    assert not limiter.blocked("alice", "1.2.3.4", now=100.0)


def test_keys_are_independent():
    limiter = FailedAttemptLimiter(max_failures=1, window_seconds=900)
    limiter.record_failure("alice", "1.2.3.4", now=100.0)
    assert not limiter.blocked("alice", "5.6.7.8", now=100.0)
    assert not limiter.blocked("bob", "1.2.3.4", now=100.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_rate_limit.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement**

```python
# src/resume_agent/api/rate_limit.py
"""In-process fixed-window throttle for failed login/register attempts.

Single-process server, so no external store; resets on restart, which
matches the threat model (password guessing, not distributed attack). No
lockout flag on the user row — an attacker must not be able to lock the
real user out durably.
"""

from __future__ import annotations

import threading
import time


class FailedAttemptLimiter:
    def __init__(self, max_failures: int = 10, window_seconds: float = 900.0) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._failures: dict[tuple[str, str], list[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: tuple[str, str], now: float) -> list[float]:
        cutoff = now - self.window_seconds
        kept = [ts for ts in self._failures.get(key, []) if ts > cutoff]
        if kept:
            self._failures[key] = kept
        else:
            self._failures.pop(key, None)
        return kept

    def blocked(self, username: str, ip: str, *, now: float | None = None) -> bool:
        moment = time.time() if now is None else now
        with self._lock:
            return len(self._prune((username, ip), moment)) >= self.max_failures

    def record_failure(self, username: str, ip: str, *, now: float | None = None) -> None:
        moment = time.time() if now is None else now
        with self._lock:
            self._failures.setdefault((username, ip), []).append(moment)

    def reset(self, username: str, ip: str) -> None:
        with self._lock:
            self._failures.pop((username, ip), None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_rate_limit.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/api/rate_limit.py tests/api/test_rate_limit.py
git commit -m "Adds failed-attempt rate limiter for login and register"
```

---

### Task 4: Multi-user auth endpoints — login/logout/me rewrite + register

**Files:**
- Modify: `src/resume_agent/api/routers/auth.py`
- Modify: `src/resume_agent/api/schemas/auth.py` (add `RegisterRequest`, extend `MeResponse` with `role: str | None = None`)
- Modify: `src/resume_agent/api/app.py` (instantiate `app.state.login_limiter = FailedAttemptLimiter()`)
- Create: `tests/api/mu_conftest_helpers.py` — no; instead extend `tests/api/conftest.py` with the multi-user fixture below
- Test: `tests/api/test_auth_multiuser.py`

**Interfaces:**
- Consumes: Tasks 1-3, Plan 1's `provision_workspace`, `new_user_id`, `hash_password`/`verify_password`.
- Produces:
  - `POST /api/auth/register {username, password, inviteCode}` → 200 `MeResponse` (does **not** log in; client proceeds to login) with typed failures `INVITE_INVALID`/`INVITE_EXPIRED`/`INVITE_USED`/`USERNAME_TAKEN`/`RATE_LIMITED`.
  - `POST /api/auth/login` — multi-user apps authenticate against `system.db` and set a user-scoped cookie; legacy apps keep today's env-credential behavior (branch on `request.app.state.system_engine is None`).
  - `GET /api/auth/me` returns `{username, role, authRequired}` for the active session.
  - Pytest fixture `mu_client` (multi-user app on a tmp data root with seeded admin `owner`/password `pw`, plus helper `login(client, username, password)`).

- [ ] **Step 1: Add the shared multi-user fixture to `tests/api/conftest.py`**

```python
# append to tests/api/conftest.py
import pytest
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.api.auth import hash_password


@pytest.fixture
def mu_app(tmp_path):
    """Multi-user app on a temp data root; admin 'owner' with password 'pw'."""
    env = tmp_path / ".env"
    env.write_text(
        f"AUTH_USERNAME=owner\n"
        f"AUTH_PASSWORD_HASH={hash_password('pw')}\n"
        f"SESSION_SECRET=test-session-secret\n",
        encoding="utf-8",
    )
    app = create_app(
        db_url=f"sqlite:///{(tmp_path / 'data' / 'seed.db').as_posix()}",
        env_path=env,
        data_dir=tmp_path / "data",
        runs_root=tmp_path / "runs",
        config_dir=tmp_path / "config",
    )
    return app


@pytest.fixture
def mu_client(mu_app):
    with TestClient(mu_app) as client:
        yield client


def login(client: TestClient, username: str = "owner", password: str = "pw"):
    response = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return response
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/api/test_auth_multiuser.py
from sqlalchemy.orm import Session

from resume_agent.tenancy.secrets import hash_secret, mint_secret
from resume_agent.tenancy.system_db import InviteCode, User

from tests.api.conftest import login


def _mint_invite(app, *, code=None, **overrides):
    from datetime import datetime, timedelta, timezone

    raw = code or mint_secret("inv_")
    values = dict(
        id="inv1",
        code_hash=hash_secret(raw),
        created_by="seed",
        expires_at=datetime.now(timezone.utc) + timedelta(days=14),
    )
    values.update(overrides)
    with Session(app.state.system_engine) as session:
        session.add(InviteCode(**values))
        session.commit()
    return raw


def test_login_sets_user_scoped_cookie(mu_client):
    response = login(mu_client)
    body = response.json()
    assert body["username"] == "owner"
    assert body["role"] == "admin"
    assert "ra_session" in mu_client.cookies


def test_login_rejects_bad_password(mu_client):
    response = mu_client.post("/api/auth/login", json={"username": "owner", "password": "nope"})
    assert response.status_code == 401


def test_register_with_valid_invite_creates_user_and_workspace(mu_app, mu_client):
    raw = _mint_invite(mu_app)
    response = mu_client.post(
        "/api/auth/register",
        json={"username": "alice", "password": "alicepw", "inviteCode": raw},
    )
    assert response.status_code == 200
    with Session(mu_app.state.system_engine) as session:
        user = session.query(User).filter_by(username="alice").one()
        assert user.role == "user"
        invite = session.get(InviteCode, "inv1")
        assert invite.used_by == user.id and invite.used_at is not None
    workspace = mu_app.state.data_dir / "users" / user.id
    assert workspace.is_dir()
    login(mu_client, "alice", "alicepw")


def test_register_rejects_unknown_and_used_and_expired(mu_app, mu_client):
    assert mu_client.post(
        "/api/auth/register",
        json={"username": "x", "password": "p", "inviteCode": "inv_bogus"},
    ).json()["error"]["code"] == "INVITE_INVALID"

    raw = _mint_invite(mu_app)
    ok = mu_client.post(
        "/api/auth/register", json={"username": "a1", "password": "p1", "inviteCode": raw}
    )
    assert ok.status_code == 200
    again = mu_client.post(
        "/api/auth/register", json={"username": "a2", "password": "p2", "inviteCode": raw}
    )
    assert again.json()["error"]["code"] == "INVITE_USED"

    from datetime import datetime, timedelta, timezone
    expired = _mint_invite(
        mu_app, id="inv2",
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    response = mu_client.post(
        "/api/auth/register", json={"username": "a3", "password": "p3", "inviteCode": expired}
    )
    assert response.json()["error"]["code"] == "INVITE_EXPIRED"


def test_register_duplicate_username(mu_app, mu_client):
    raw = _mint_invite(mu_app)
    response = mu_client.post(
        "/api/auth/register", json={"username": "owner", "password": "p", "inviteCode": raw}
    )
    assert response.json()["error"]["code"] == "USERNAME_TAKEN"


def test_login_rate_limited_after_failures(mu_client):
    for _ in range(10):
        mu_client.post("/api/auth/login", json={"username": "owner", "password": "bad"})
    blocked = mu_client.post("/api/auth/login", json={"username": "owner", "password": "pw"})
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMITED"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_auth_multiuser.py -v`
Expected: FAIL — no register route; login ignores system.db

- [ ] **Step 4: Implement**

Schemas (`src/resume_agent/api/schemas/auth.py`) — add:

```python
class RegisterRequest(CamelModel):
    username: str
    password: str
    invite_code: str
```

and add `role: str | None = None` to `MeResponse`.

`app.py`: add `from resume_agent.api.rate_limit import FailedAttemptLimiter` and, next to the other `app.state` assignments, `app.state.login_limiter = FailedAttemptLimiter()`.

Rewrite `src/resume_agent/api/routers/auth.py`:

```python
"""Login/logout/me/register. Multi-user apps authenticate against system.db;
legacy apps (no system engine) keep the env-credential single account."""

from __future__ import annotations

import hmac
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from resume_agent.api import auth
from resume_agent.api.deps import get_settings_dep
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.auth import LoginRequest, MeResponse, RegisterRequest
from resume_agent.config import Settings
from resume_agent.tenancy.context import new_user_id
from resume_agent.tenancy.secrets import hash_secret
from resume_agent.tenancy.system_db import InviteCode, User
from resume_agent.tenancy.workspace import provision_workspace

router = APIRouter(prefix="/auth", tags=["auth"])
FAILED_LOGIN_DELAY_SECONDS = 1.0


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _rate_gate(request: Request, username: str) -> None:
    limiter = request.app.state.login_limiter
    if limiter.blocked(username, _client_ip(request)):
        raise ApiException(429, "RATE_LIMITED", "Too many failed attempts; try again later")


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        auth.SESSION_COOKIE,
        token,
        max_age=auth.SESSION_LIFETIME_SECONDS,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


@router.post("/login")
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings_dep),
) -> MeResponse:
    system_engine = request.app.state.system_engine
    if system_engine is None:
        return _legacy_login(body, response, settings)

    _rate_gate(request, body.username)
    limiter = request.app.state.login_limiter
    with Session(system_engine) as session:
        user = session.execute(
            select(User).where(User.username == body.username)
        ).scalars().first()
    if user is None or not auth.verify_password(body.password, user.password_hash):
        limiter.record_failure(body.username, _client_ip(request))
        time.sleep(FAILED_LOGIN_DELAY_SECONDS)
        raise ApiException(401, "UNAUTHORIZED", "Invalid username or password")
    if user.disabled_at is not None:
        raise ApiException(403, "USER_DISABLED", "This account is disabled")
    limiter.reset(body.username, _client_ip(request))
    token = auth.issue_user_session(
        settings, user_id=user.id, password_hash=user.password_hash
    )
    _set_session_cookie(response, token)
    return MeResponse(username=user.username, role=user.role, auth_required=True)


def _legacy_login(body: LoginRequest, response: Response, settings: Settings) -> MeResponse:
    if not auth.session_auth_configured(settings):
        raise ApiException(400, "AUTH_NOT_CONFIGURED", "Session auth is not configured")
    username_ok = hmac.compare_digest(body.username.encode(), settings.auth_username.encode())
    password_ok = auth.verify_password(body.password, settings.auth_password_hash)
    if not (username_ok and password_ok):
        time.sleep(FAILED_LOGIN_DELAY_SECONDS)
        raise ApiException(401, "UNAUTHORIZED", "Invalid username or password")
    _set_session_cookie(response, auth.issue_session(settings))
    return MeResponse(username=settings.auth_username, auth_required=True)


@router.post("/register")
def register(body: RegisterRequest, request: Request) -> MeResponse:
    system_engine = request.app.state.system_engine
    if system_engine is None:
        raise ApiException(400, "AUTH_NOT_CONFIGURED", "Registration requires multi-user mode")
    _rate_gate(request, body.username)
    limiter = request.app.state.login_limiter
    now = datetime.now(timezone.utc)
    code_hash = hash_secret(body.invite_code)
    with Session(system_engine) as session:
        invite = session.execute(
            select(InviteCode).where(InviteCode.code_hash == code_hash)
        ).scalars().first()
        if invite is None or invite.revoked_at is not None:
            limiter.record_failure(body.username, _client_ip(request))
            raise ApiException(400, "INVITE_INVALID", "Unknown invitation code")
        expires_at = invite.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            raise ApiException(400, "INVITE_EXPIRED", "This invitation code has expired")
        if invite.used_at is not None:
            raise ApiException(400, "INVITE_USED", "This invitation code was already used")
        existing = session.execute(
            select(User).where(User.username == body.username)
        ).scalars().first()
        if existing is not None:
            raise ApiException(409, "USERNAME_TAKEN", "That username is taken")
        user = User(
            id=new_user_id(),
            username=body.username,
            password_hash=auth.hash_password(body.password),
            role="user",
        )
        session.add(user)
        # Atomic consume: the guarded UPDATE loses the race cleanly if a
        # concurrent registration consumed the code between read and write.
        consumed = session.execute(
            update(InviteCode)
            .where(InviteCode.id == invite.id, InviteCode.used_at.is_(None))
            .values(used_by=user.id, used_at=now)
        )
        if consumed.rowcount != 1:
            session.rollback()
            raise ApiException(400, "INVITE_USED", "This invitation code was already used")
        session.commit()
        user_id, username, role = user.id, user.username, user.role
    provision_workspace(request.app.state.data_dir, user_id)
    limiter.reset(body.username, _client_ip(request))
    return MeResponse(username=username, role=role, auth_required=True)


@router.post("/logout")
def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return {"status": "ok"}


@router.get("/me")
def me(request: Request, settings: Settings = Depends(get_settings_dep)) -> MeResponse:
    system_engine = request.app.state.system_engine
    token = request.cookies.get(auth.SESSION_COOKIE, "")
    if system_engine is None:
        if not auth.session_auth_configured(settings):
            return MeResponse(auth_required=False)
        return MeResponse(username=auth.verify_session(token, settings), auth_required=True)
    user_id = auth.parse_session_user_id(token)
    if user_id is None:
        return MeResponse(auth_required=True)
    with Session(system_engine) as session:
        user = session.get(User, user_id)
    if user is None or auth.verify_user_session(
        token, settings, password_hash=user.password_hash
    ) is None:
        return MeResponse(auth_required=True)
    return MeResponse(username=user.username, role=user.role, auth_required=True)
```

Note: `TestClient` sends cookies over http; if `secure=True` cookies don't round-trip in tests, follow the repo's existing session-test precedent (the Railway login tests already handle this — mirror whatever they do).

- [ ] **Step 5: Run tests + full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_auth_multiuser.py -v` → 6 passed
Run: `.venv/Scripts/python.exe -m pytest -q && ruff check` → green (legacy login tests still pass through `_legacy_login`).

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/api/routers/auth.py src/resume_agent/api/schemas/auth.py src/resume_agent/api/app.py tests/api/conftest.py tests/api/test_auth_multiuser.py
git commit -m "Adds invite-code registration and system.db-backed login"
```

---

### Task 5: PATs + unified per-request auth resolution

**Files:**
- Create: `src/resume_agent/api/routers/account.py` (PAT endpoints; Plan 3 adds password-change/export here)
- Create: `src/resume_agent/api/schemas/account.py`
- Modify: `src/resume_agent/api/deps.py` (`get_user_context` becomes the real resolver)
- Modify: `src/resume_agent/api/app.py` (include `account` router in guarded list)
- Test: `tests/api/test_pats.py`, `tests/api/test_tenancy_isolation.py`

**Interfaces:**
- Consumes: Task 2 crypto, Task 4 fixture, Plan 1 `build_context`.
- Produces:
  - `POST /api/account/tokens {name}` → `{id, name, token}` (raw `rat_…` shown once); `GET /api/account/tokens` → list (no hashes); `DELETE /api/account/tokens/{id}` → revoke.
  - `get_user_context` resolution chain for multi-user apps: session cookie → `Authorization: Bearer rat_…` (header-only) → `?token=` link token (query-only) → 401 `UNAUTHORIZED`; disabled users → 403 `USER_DISABLED`. Legacy apps: unchanged Plan 1 behavior (default context after `require_token`).
  - Every guarded route now serves **the authenticated user's own workspace** — Plan 1's `default_context` is only used by legacy apps.

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_pats.py
from tests.api.conftest import login


def test_mint_list_revoke_pat(mu_client):
    login(mu_client)
    minted = mu_client.post("/api/account/tokens", json={"name": "cli"})
    assert minted.status_code == 200
    body = minted.json()
    raw = body["token"]
    assert raw.startswith("rat_")

    listed = mu_client.get("/api/account/tokens").json()
    assert [t["name"] for t in listed["tokens"]] == ["cli"]
    assert "token" not in listed["tokens"][0]

    mu_client.cookies.clear()
    with_pat = mu_client.get("/api/jobs", headers={"Authorization": f"Bearer {raw}"})
    assert with_pat.status_code == 200

    login(mu_client)
    revoked = mu_client.delete(f"/api/account/tokens/{body['id']}")
    assert revoked.status_code == 200
    mu_client.cookies.clear()
    after = mu_client.get("/api/jobs", headers={"Authorization": f"Bearer {raw}"})
    assert after.status_code == 401


def test_pat_rejected_in_query_param(mu_client):
    login(mu_client)
    raw = mu_client.post("/api/account/tokens", json={"name": "x"}).json()["token"]
    mu_client.cookies.clear()
    assert mu_client.get(f"/api/jobs?token={raw}").status_code == 401


def test_unauthenticated_guarded_route_is_401(mu_client):
    assert mu_client.get("/api/jobs").status_code == 401
    assert mu_client.get("/api/health").status_code == 200
```

```python
# tests/api/test_tenancy_isolation.py
from sqlalchemy.orm import Session
from sqlmodel import Session as SMSession

from resume_agent.tracking.tables import Job
from resume_agent.tenancy.secrets import hash_secret, mint_secret
from resume_agent.tenancy.system_db import InviteCode

from tests.api.conftest import login


def _register(mu_app, mu_client, username):
    from datetime import datetime, timedelta, timezone

    raw = mint_secret("inv_")
    with Session(mu_app.state.system_engine) as session:
        session.add(InviteCode(
            id=f"inv-{username}", code_hash=hash_secret(raw), created_by="seed",
            expires_at=datetime.now(timezone.utc) + timedelta(days=14),
        ))
        session.commit()
    response = mu_client.post(
        "/api/auth/register",
        json={"username": username, "password": "pw", "inviteCode": raw},
    )
    assert response.status_code == 200


def test_users_see_only_their_own_jobs(mu_app, mu_client):
    _register(mu_app, mu_client, "alice")
    login(mu_client, "alice", "pw")
    # seed a job directly into alice's workspace engine
    ctx_registry = mu_app.state.engine_registry
    from sqlalchemy.orm import Session as SA
    from resume_agent.tenancy.system_db import User
    with SA(mu_app.state.system_engine) as s:
        alice = s.query(User).filter_by(username="alice").one()
    from resume_agent.tenancy.workspace import workspace_paths
    engine = ctx_registry.get(alice.id, workspace_paths(mu_app.state.data_dir, alice.id).db_url)
    with SMSession(engine) as session:
        session.add(Job(source="manual", jd_text="alice job", company="A", title="Eng"))
        session.commit()

    assert len(mu_client.get("/api/jobs").json()["items"]) == 1

    login(mu_client, "owner", "pw")
    assert mu_client.get("/api/jobs").json()["items"] == []
```

Note: check the actual `/api/jobs` response shape (`items` vs a bare list) in `api/routers/jobs.py` and match it.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_pats.py tests/api/test_tenancy_isolation.py -v`
Expected: FAIL — no account router; guarded routes still serve the default (admin) context for everyone

- [ ] **Step 3: Implement the account router**

```python
# src/resume_agent/api/schemas/account.py
from datetime import datetime

from resume_agent.api.schemas.base import CamelModel


class TokenCreateRequest(CamelModel):
    name: str


class TokenCreated(CamelModel):
    id: str
    name: str
    token: str  # raw secret — shown exactly once


class TokenInfo(CamelModel):
    id: str
    name: str
    created_at: datetime
    last_used_at: datetime | None = None


class TokenList(CamelModel):
    tokens: list[TokenInfo]
```

```python
# src/resume_agent/api/routers/account.py
"""Self-service account surface: personal access tokens (Plan 3 adds
password change and workspace export)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.account import (
    TokenCreated,
    TokenCreateRequest,
    TokenInfo,
    TokenList,
)
from resume_agent.tenancy.context import require_context
from resume_agent.tenancy.secrets import hash_secret, mint_secret
from resume_agent.tenancy.system_db import ApiToken

router = APIRouter(prefix="/account", tags=["account"])


@router.post("/tokens")
def mint_token(body: TokenCreateRequest, request: Request) -> TokenCreated:
    ctx = require_context()
    raw = mint_secret("rat_")
    row = ApiToken(
        id=uuid.uuid4().hex[:12],
        user_id=ctx.user_id,
        name=body.name,
        token_hash=hash_secret(raw),
    )
    with Session(request.app.state.system_engine) as session:
        session.add(row)
        session.commit()
    return TokenCreated(id=row.id, name=row.name, token=raw)


@router.get("/tokens")
def list_tokens(request: Request) -> TokenList:
    ctx = require_context()
    with Session(request.app.state.system_engine) as session:
        rows = session.execute(
            select(ApiToken)
            .where(ApiToken.user_id == ctx.user_id, ApiToken.revoked_at.is_(None))
            .order_by(ApiToken.created_at)
        ).scalars().all()
        return TokenList(tokens=[TokenInfo.model_validate(row) for row in rows])


@router.delete("/tokens/{token_id}")
def revoke_token(token_id: str, request: Request) -> dict[str, str]:
    ctx = require_context()
    with Session(request.app.state.system_engine) as session:
        row = session.get(ApiToken, token_id)
        if row is None or row.user_id != ctx.user_id:
            raise ApiException(404, "NOT_FOUND", "No such token")
        row.revoked_at = datetime.now(timezone.utc)
        session.commit()
    return {"status": "revoked"}
```

Register in `app.py`: `from resume_agent.api.routers import account as account_router` and `app.include_router(account_router.router, prefix="/api", dependencies=guarded)`.

- [ ] **Step 4: Implement the real `get_user_context`**

Replace Plan 1's transitional body in `src/resume_agent/api/deps.py`:

```python
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session as SASession

from resume_agent.api import auth as auth_mod
from resume_agent.tenancy.bootstrap import build_context
from resume_agent.tenancy.context import UserContext, current_context, use_context
from resume_agent.tenancy.secrets import hash_secret
from resume_agent.tenancy.system_db import ApiToken, User


def _resolve_user(request: Request, settings: Settings):
    """Session cookie -> PAT bearer (header-only) -> link token (query-only)."""
    system_engine = request.app.state.system_engine
    with SASession(system_engine) as session:
        cookie = request.cookies.get(auth_mod.SESSION_COOKIE, "")
        user_id = auth_mod.parse_session_user_id(cookie)
        if user_id is not None:
            user = session.get(User, user_id)
            if user is not None and auth_mod.verify_user_session(
                cookie, settings, password_hash=user.password_hash
            ):
                session.expunge(user)
                return user

        header = request.headers.get("authorization", "")
        if header.startswith("Bearer rat_"):
            raw = header.removeprefix("Bearer ").strip()
            row = session.execute(
                select(ApiToken).where(
                    ApiToken.token_hash == hash_secret(raw),
                    ApiToken.revoked_at.is_(None),
                )
            ).scalars().first()
            if row is not None:
                row.last_used_at = datetime.now(timezone.utc)
                user = session.get(User, row.user_id)
                session.commit()
                if user is not None:
                    session.expunge(user)
                    return user

        query_token = request.query_params.get("token")
        if query_token:
            verified = auth_mod.verify_link_token(query_token, settings)
            if verified is not None:
                user = session.get(User, verified[0])
                if user is not None:
                    session.expunge(user)
                    return user
    return None


def get_user_context(
    request: Request,
    settings: Settings = Depends(get_settings_dep),
) -> Iterator[UserContext | None]:
    """The request set-point of ADR-0003."""
    if request.app.state.system_engine is None:
        # Legacy app: require_token already gated; no tenancy.
        ctx = getattr(request.app.state, "default_context", None)
        if ctx is None:
            yield None
            return
        with use_context(ctx):
            yield ctx
        return
    user = _resolve_user(request, request.app.state.settings)
    if user is None:
        raise ApiException(401, "UNAUTHORIZED", "Missing or invalid credentials")
    if user.disabled_at is not None:
        raise ApiException(403, "USER_DISABLED", "This account is disabled")
    ctx = build_context(
        user,
        request.app.state.data_dir,
        request.app.state.settings,
        request.app.state.engine_registry,
    )
    with use_context(ctx):
        yield ctx
```

Also update `require_token` so multi-user apps defer entirely to `get_user_context` (insert at the top of `require_token`):

```python
    if getattr(request.app.state, "system_engine", None) is not None:
        return  # multi-user apps authenticate in get_user_context
```

Note the resolver uses `request.app.state.settings` (platform settings) for signature verification — not the per-user effective settings, which don't exist until after resolution.

- [ ] **Step 5: Run new tests + full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_pats.py tests/api/test_tenancy_isolation.py tests/api/test_auth_multiuser.py -v` → all pass
Run: `.venv/Scripts/python.exe -m pytest -q && ruff check` → green. Plan 1's `test_guarded_route_runs_inside_default_context` now needs a login first — update that test to call `login(...)` (its app has creds `owner/pw` only if it used `hash_password`; align the fixture with `mu_app`).

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/api/routers/account.py src/resume_agent/api/schemas/account.py src/resume_agent/api/deps.py src/resume_agent/api/app.py tests/api/test_pats.py tests/api/test_tenancy_isolation.py tests/api/test_multi_user_boot.py
git commit -m "Adds PATs and per-user request auth resolution"
```

---

### Task 6: Link-token endpoint + SPA plumbing

**Files:**
- Modify: `src/resume_agent/api/routers/auth.py` (add `/auth/link-token`)
- Modify: `src/resume_agent/api/schemas/auth.py` (add `LinkTokenResponse`)
- Modify: `web/src/lib/api` (add `fetchLinkToken`) and the SSE/download call sites
- Test: `tests/api/test_link_tokens.py`

**Interfaces:**
- Produces: `POST /api/auth/link-token {purpose: "sse" | "download"}` → `{token, expiresInSeconds}` (guarded route — caller is already authenticated via cookie). The SPA requests a fresh link token immediately before opening an `EventSource` or building a download `href`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_link_tokens.py
from tests.api.conftest import login


def test_link_token_grants_query_access(mu_client):
    login(mu_client)
    minted = mu_client.post("/api/auth/link-token", json={"purpose": "sse"})
    assert minted.status_code == 200
    token = minted.json()["token"]

    mu_client.cookies.clear()
    response = mu_client.get(f"/api/jobs?token={token}")
    assert response.status_code == 200


def test_link_token_requires_auth_to_mint(mu_client):
    assert mu_client.post("/api/auth/link-token", json={"purpose": "sse"}).status_code == 401


def test_garbage_query_token_rejected(mu_client):
    assert mu_client.get("/api/jobs?token=garbage").status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_link_tokens.py -v`
Expected: FAIL — 404 on the mint route

- [ ] **Step 3: Implement the endpoint**

Schema: add to `api/schemas/auth.py`:

```python
class LinkTokenRequest(CamelModel):
    purpose: str


class LinkTokenResponse(CamelModel):
    token: str
    expires_in_seconds: int
```

Router — this route must be **guarded** (it authenticates via the normal chain), so register it as a separate router in `auth.py` and include it with `dependencies=guarded` in `app.py`:

```python
# append to src/resume_agent/api/routers/auth.py
from resume_agent.api.schemas.auth import LinkTokenRequest, LinkTokenResponse
from resume_agent.tenancy.context import require_context

link_router = APIRouter(prefix="/auth", tags=["auth"])


@link_router.post("/link-token")
def mint_link_token(
    body: LinkTokenRequest,
    settings: Settings = Depends(get_settings_dep),
) -> LinkTokenResponse:
    ctx = require_context()
    if body.purpose not in {"sse", "download"}:
        raise ApiException(400, "VALIDATION", "purpose must be 'sse' or 'download'")
    token = auth.issue_link_token(
        settings, user_id=ctx.user_id, purpose=body.purpose
    )
    return LinkTokenResponse(token=token, expires_in_seconds=auth.LINK_TOKEN_TTL_SECONDS)
```

In `app.py`: `app.include_router(auth_router.link_router, prefix="/api", dependencies=guarded)` (the plain `auth_router.router` stays unguarded for login/register).

Note: `settings` here must be the platform settings used for verification; in multi-user requests `get_settings_dep` is overridden to `app.state.settings`, which is correct.

- [ ] **Step 4: SPA plumbing**

First locate current static-token usage: run `grep -rn "token=" web/src` and `grep -rn "EventSource" web/src`. Add the helper to the API lib (adapt the path to the existing module layout under `web/src/lib/api`):

```typescript
// web/src/lib/api/linkToken.ts
export async function fetchLinkToken(purpose: "sse" | "download"): Promise<string> {
  const response = await fetch("/api/auth/link-token", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ purpose }),
  });
  if (!response.ok) throw new Error(`link token failed: ${response.status}`);
  const body = (await response.json()) as { token: string };
  return body.token;
}
```

At each `EventSource` construction found by the grep, fetch a token first:

```typescript
const token = await fetchLinkToken("sse");
const source = new EventSource(`/api/runs/${runId}/events?token=${encodeURIComponent(token)}`);
```

At each download `href` builder, do the same with `"download"` — since minting is async, convert static `href`s into click handlers that fetch the token then set `window.location`. Run the web tests (`cd web && npx vitest run`) and fix any mocked-fetch expectations the change breaks.

- [ ] **Step 5: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_link_tokens.py -v` → 3 passed
Run: `cd web && npx vitest run` → green

- [ ] **Step 6: Commit**

```bash
git add src/resume_agent/api/routers/auth.py src/resume_agent/api/schemas/auth.py src/resume_agent/api/app.py web/src tests/api/test_link_tokens.py
git commit -m "Adds short-lived link tokens for SSE and downloads"
```

---

### Task 7: Usage recording at the acall leaf

**Files:**
- Create: `src/resume_agent/tenancy/usage.py`
- Modify: `src/resume_agent/llm_runner.py:300-314` (`acall`)
- Modify: `src/resume_agent/api/app.py` + `src/resume_agent/tenancy/local.py` (configure the recorder)
- Test: `tests/tenancy/test_usage.py`

**Interfaces:**
- Produces:
  - `usage.configure(engine: Engine | None) -> None` (module-level; app lifespan and CLI local-context activation call it; tests call `configure(None)` to reset).
  - `usage.record_call(agent, response) -> None` — extracts model/metrics defensively, computes `weighted_total`, determines `own_key`, appends a `UsageEvent`. **Never raises**; no-ops without a configured engine or active context.
  - Weights: `input=1.0`, `output=3.0`, `cache_read=0.1`, `cache_creation=1.25` (module constants).
- Before implementing, check the exact shapes in `llm_runner.py`: the return type of `split_provider` and what `AgentRunner.arun` returns (agno `RunOutput` — its `metrics` attribute carries `input_tokens`/`output_tokens`/`cache_read_tokens`/`cache_creation_tokens`, possibly as lists to sum). Adapt `_metrics_from_response` accordingly.

- [ ] **Step 1: Write the failing tests**

```python
# tests/tenancy/test_usage.py
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from resume_agent.config import Settings
from resume_agent.tenancy import usage
from resume_agent.tenancy.context import use_context
from resume_agent.tenancy.system_db import UsageEvent, init_system_db, make_system_engine

from tests.tenancy.test_context import make_ctx


class FakeAgent:
    model_id = "claude-sonnet-5"


def fake_response(input_tokens=100, output_tokens=50):
    return SimpleNamespace(
        metrics=SimpleNamespace(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=0,
            cache_creation_tokens=0,
        )
    )


@pytest.fixture
def engine(tmp_path):
    eng = make_system_engine(tmp_path)
    init_system_db(eng)
    usage.configure(eng)
    yield eng
    usage.configure(None)
    eng.dispose()


def test_records_event_with_weighted_total(engine):
    ctx = make_ctx()
    with use_context(ctx):
        usage.record_call(FakeAgent(), fake_response())
    with Session(engine) as session:
        event = session.execute(select(UsageEvent)).scalars().one()
        assert event.user_id == ctx.user_id
        assert event.model == "claude-sonnet-5"
        assert event.weighted_total == 100 * 1.0 + 50 * 3.0
        assert event.own_key is False


def test_own_key_flag_when_user_key_differs(engine):
    user_settings = Settings(_env_file=None, anthropic_api_key="user-key")
    ctx = make_ctx(settings=user_settings)
    with use_context(ctx):
        usage.record_call(FakeAgent(), fake_response())
    with Session(engine) as session:
        assert session.execute(select(UsageEvent)).scalars().one().own_key is True


def test_noop_without_context(engine):
    usage.record_call(FakeAgent(), fake_response())
    with Session(engine) as session:
        assert session.execute(select(UsageEvent)).scalars().all() == []


def test_noop_without_configuration(tmp_path):
    usage.configure(None)
    with use_context(make_ctx()):
        usage.record_call(FakeAgent(), fake_response())  # must not raise


def test_never_raises_on_garbage_response(engine):
    with use_context(make_ctx()):
        usage.record_call(FakeAgent(), object())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/tenancy/test_usage.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement**

```python
# src/resume_agent/tenancy/usage.py
"""Best-effort per-call usage recording (the acall leaf's side channel).

Recording never breaks the call: any failure logs a warning and the LLM
result still returns. Enforcement (tenancy/limits.py) reads whatever was
recorded. own_key rows are recorded for visibility but exempt from budgets.
"""

from __future__ import annotations

import logging

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from resume_agent.config import Settings, env_settings
from resume_agent.tenancy.context import current_context
from resume_agent.tenancy.system_db import UsageEvent

logger = logging.getLogger(__name__)

WEIGHT_INPUT = 1.0
WEIGHT_OUTPUT = 3.0
WEIGHT_CACHE_READ = 0.1
WEIGHT_CACHE_CREATION = 1.25

_PROVIDER_KEY_FIELDS = {
    "anthropic": "anthropic_api_key",
    "openai": "openai_api_key",
    "gemini": "gemini_api_key",
    "deepseek": "deepseek_api_key",
}

_engine: Engine | None = None


def configure(engine: Engine | None) -> None:
    global _engine
    _engine = engine


def _int_metric(metrics: object, name: str) -> int:
    value = getattr(metrics, name, 0) or 0
    if isinstance(value, (list, tuple)):  # agno versions aggregate as lists
        value = sum(v or 0 for v in value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _model_id(agent: object) -> str:
    for attr in ("model_id",):
        value = getattr(agent, attr, None)
        if isinstance(value, str) and value:
            return value
    model = getattr(agent, "model", None) or getattr(getattr(agent, "agent", None), "model", None)
    return str(getattr(model, "id", "") or "")


def _is_own_key(model_id: str, ctx_settings: Settings) -> bool:
    from resume_agent.llm_runner import split_provider

    provider = split_provider(model_id)[0]
    field = _PROVIDER_KEY_FIELDS.get(provider, "anthropic_api_key")
    user_key = getattr(ctx_settings, field, "") or ""
    server_key = getattr(env_settings(), field, "") or ""
    return bool(user_key) and user_key != server_key


def record_call(agent: object, response: object) -> None:
    if _engine is None:
        return
    ctx = current_context()
    if ctx is None:
        return
    try:
        metrics = getattr(response, "metrics", None)
        input_tokens = _int_metric(metrics, "input_tokens")
        output_tokens = _int_metric(metrics, "output_tokens")
        cache_read = _int_metric(metrics, "cache_read_tokens")
        cache_creation = _int_metric(metrics, "cache_creation_tokens")
        model_id = _model_id(agent)
        from resume_agent.llm_runner import split_provider

        provider = split_provider(model_id)[0] if model_id else None
        event = UsageEvent(
            user_id=ctx.user_id,
            provider=provider,
            model=model_id or None,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read,
            cache_creation_tokens=cache_creation,
            weighted_total=(
                input_tokens * WEIGHT_INPUT
                + output_tokens * WEIGHT_OUTPUT
                + cache_read * WEIGHT_CACHE_READ
                + cache_creation * WEIGHT_CACHE_CREATION
            ),
            own_key=_is_own_key(model_id, ctx.settings) if model_id else False,
        )
        with Session(_engine) as session:
            session.add(event)
            session.commit()
    except Exception:  # noqa: BLE001 — accounting must never break the call
        logger.warning("usage recording failed", exc_info=True)
```

Verify `split_provider`'s return shape in `llm_runner.py` (`(provider, model)` tuple is assumed; adapt `[0]` if it differs).

Integrate in `llm_runner.acall` (line ~309):

```python
    async with sem:
        _observe(on_acquire)
        try:
            response = await agent.arun(prompt)
            from resume_agent.tenancy import usage

            usage.record_call(agent, response)
            return response
        finally:
            _observe(on_release)
```

Configure at both server and CLI set-points:
- `app.py` lifespan multi-user branch: `from resume_agent.tenancy import usage` → `usage.configure(system_engine)`; legacy branch: `usage.configure(None)`.
- `tenancy/local.py` `activate_local_context`: after resolving a multi-user context, `usage.configure(make_system_engine(root))` — construct one engine and keep it (module-lifetime is fine for a CLI process).

- [ ] **Step 4: Run tests + full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/tenancy/test_usage.py -v` → 5 passed
Run: `.venv/Scripts/python.exe -m pytest -q && ruff check` → green (fakes in the agent-suite return objects without `metrics`; recording no-ops).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tenancy/usage.py src/resume_agent/llm_runner.py src/resume_agent/api/app.py src/resume_agent/tenancy/local.py tests/tenancy/test_usage.py
git commit -m "Records per-user LLM usage at the acall leaf"
```

---

### Task 8: Budget enforcement at phase entrypoints

**Files:**
- Create: `src/resume_agent/tenancy/limits.py`
- Modify: the LLM-phase service entrypoints (locate with `grep -n "^def " src/resume_agent/services/discovery.py src/resume_agent/services/tailoring.py src/resume_agent/services/cover_letters.py src/resume_agent/services/profile_build.py` — add the two-line guard to each public function that fans out LLM calls: discovery extract/score, `tailor`, `write_cover_letters`, `run_corpus_build`)
- Test: `tests/tenancy/test_limits.py`

**Interfaces:**
- Produces:
  - Constants: `DEFAULT_WEEKLY_TOKEN_BUDGET = 10_000_000`, `DEFAULT_MAX_ACTIVE_JOBS = 2000`, `DEFAULT_MAX_CONCURRENT_RUNS = 2`.
  - `class BudgetExceededError(RuntimeError)` with `.code = "BUDGET_EXCEEDED"`.
  - `system_default(engine, key: str, fallback: int) -> int` (reads `SystemSetting`, int-parsed).
  - `resolve_limit(override: int | None, default: int) -> int` — `None` → default; `0` → unlimited (returned as `0`).
  - `weekly_usage(engine, user_id: str, *, now: datetime | None = None) -> float` — sum of `weighted_total` where `own_key` is false and `ts >= now - 7 days`.
  - `enforce_budget(engine, *, user_id: str, role: str, budget_override: int | None, now=None) -> None` — admins exempt; `0` = unlimited; raises `BudgetExceededError`.
  - `enforce_active_budget() -> None` — module-level convenience: reads `current_context()` and the usage-configured engine; silently no-ops when either is absent (legacy/tests). Services call **only this**.

- [ ] **Step 1: Write the failing tests**

```python
# tests/tenancy/test_limits.py
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.orm import Session

from resume_agent.tenancy import usage
from resume_agent.tenancy.context import use_context
from resume_agent.tenancy.limits import (
    DEFAULT_WEEKLY_TOKEN_BUDGET,
    BudgetExceededError,
    enforce_active_budget,
    enforce_budget,
    resolve_limit,
    weekly_usage,
)
from resume_agent.tenancy.system_db import UsageEvent, init_system_db, make_system_engine

from tests.tenancy.test_context import make_ctx

NOW = datetime(2026, 7, 12, tzinfo=timezone.utc)


@pytest.fixture
def engine(tmp_path):
    eng = make_system_engine(tmp_path)
    init_system_db(eng)
    yield eng
    eng.dispose()


def _add_usage(engine, user_id, weighted, *, days_ago=0.0, own_key=False):
    with Session(engine) as session:
        session.add(UsageEvent(
            user_id=user_id, ts=NOW - timedelta(days=days_ago),
            weighted_total=weighted, own_key=own_key,
        ))
        session.commit()


def test_resolve_limit():
    assert resolve_limit(None, 10) == 10
    assert resolve_limit(5, 10) == 5
    assert resolve_limit(0, 10) == 0  # 0 = unlimited


def test_weekly_usage_windows_and_own_key(engine):
    _add_usage(engine, "u1", 100.0)
    _add_usage(engine, "u1", 100.0, days_ago=8)      # outside window
    _add_usage(engine, "u1", 100.0, own_key=True)    # exempt
    _add_usage(engine, "u2", 100.0)                  # other user
    assert weekly_usage(engine, "u1", now=NOW) == 100.0


def test_enforce_budget_raises_over_budget(engine):
    _add_usage(engine, "u1", 200.0)
    with pytest.raises(BudgetExceededError):
        enforce_budget(engine, user_id="u1", role="user", budget_override=100, now=NOW)
    enforce_budget(engine, user_id="u1", role="user", budget_override=300, now=NOW)


def test_admin_and_unlimited_exempt(engine):
    _add_usage(engine, "u1", 10**12)
    enforce_budget(engine, user_id="u1", role="admin", budget_override=100, now=NOW)
    enforce_budget(engine, user_id="u1", role="user", budget_override=0, now=NOW)


def test_enforce_active_budget_reads_context(engine):
    usage.configure(engine)
    try:
        _add_usage(engine, "abc123def456", float(DEFAULT_WEEKLY_TOKEN_BUDGET + 1))
        with use_context(make_ctx()):
            with pytest.raises(BudgetExceededError):
                enforce_active_budget(now=NOW)
        enforce_active_budget(now=NOW)  # no context -> no-op
    finally:
        usage.configure(None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/tenancy/test_limits.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement**

```python
# src/resume_agent/tenancy/limits.py
"""Budget and quota resolution/enforcement.

Budgets are checked once per phase (never inside the semaphore-guarded
leaf); mid-run overshoot is tolerated by design. Admins and own-key usage
are recorded but never enforced. NULL override = system default; 0 =
unlimited.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from resume_agent.tenancy import usage as usage_module
from resume_agent.tenancy.context import current_context
from resume_agent.tenancy.system_db import SystemSetting, UsageEvent, User

DEFAULT_WEEKLY_TOKEN_BUDGET = 10_000_000
DEFAULT_MAX_ACTIVE_JOBS = 2_000
DEFAULT_MAX_CONCURRENT_RUNS = 2

BUDGET_WINDOW = timedelta(days=7)


class BudgetExceededError(RuntimeError):
    code = "BUDGET_EXCEEDED"


def system_default(engine: Engine, key: str, fallback: int) -> int:
    with Session(engine) as session:
        row = session.get(SystemSetting, key)
    if row is None:
        return fallback
    try:
        return int(row.value)
    except ValueError:
        return fallback


def resolve_limit(override: int | None, default: int) -> int:
    return default if override is None else override


def weekly_usage(engine: Engine, user_id: str, *, now: datetime | None = None) -> float:
    moment = now or datetime.now(timezone.utc)
    cutoff = moment - BUDGET_WINDOW
    with Session(engine) as session:
        total = session.execute(
            select(func.coalesce(func.sum(UsageEvent.weighted_total), 0.0)).where(
                UsageEvent.user_id == user_id,
                UsageEvent.own_key.is_(False),
                UsageEvent.ts >= cutoff,
            )
        ).scalar_one()
    return float(total)


def enforce_budget(
    engine: Engine,
    *,
    user_id: str,
    role: str,
    budget_override: int | None,
    now: datetime | None = None,
) -> None:
    if role == "admin":
        return
    budget = resolve_limit(
        budget_override,
        system_default(engine, "weekly_token_budget", DEFAULT_WEEKLY_TOKEN_BUDGET),
    )
    if budget == 0:
        return
    spent = weekly_usage(engine, user_id, now=now)
    if spent >= budget:
        raise BudgetExceededError(
            f"weekly token budget exhausted ({spent:,.0f} of {budget:,} weighted tokens)"
        )


def enforce_active_budget(*, now: datetime | None = None) -> None:
    """Phase pre-flight for service entrypoints. No-ops without tenancy."""
    ctx = current_context()
    engine = usage_module._engine
    if ctx is None or engine is None:
        return
    with Session(engine) as session:
        user = session.get(User, ctx.user_id)
    override = user.weekly_token_budget if user is not None else None
    enforce_budget(
        engine, user_id=ctx.user_id, role=ctx.role, budget_override=override, now=now
    )
```

Wire the guard into each LLM-phase service entrypoint found by the grep (top of the function body, after argument validation):

```python
    from resume_agent.tenancy.limits import enforce_active_budget

    enforce_active_budget()
```

A `BudgetExceededError` raised inside a run worker surfaces as a failed run record (`RunManager` stamps `"BudgetExceededError: …"`), which is the spec's contract.

- [ ] **Step 4: Run tests + full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/tenancy/test_limits.py -v` → 5 passed
Run: `.venv/Scripts/python.exe -m pytest -q && ruff check` → green (no context in legacy tests → guard no-ops).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/tenancy/limits.py src/resume_agent/services tests/tenancy/test_limits.py
git commit -m "Enforces weekly token budgets at LLM phase entrypoints"
```

---

### Task 9: Quotas — concurrent runs and active-job cap + contract regen

**Files:**
- Modify: `src/resume_agent/api/runs/manager.py` (`create`/`submit` gain `user_id` + cap), `src/resume_agent/api/runs/models.py` (snapshot carries `user_id`)
- Modify: `src/resume_agent/api/routers/runs.py` (pass `user_id`/cap from context; 429 mapping; per-user filtering of list/get)
- Modify: `src/resume_agent/discovery/ingest.py` (job-cap gate in the `IngestCounts` loop)
- Modify: `CLAUDE.md` (limits section)
- Test: `tests/api/test_run_quota.py`, `tests/test_ingest_job_cap.py`

**Interfaces:**
- Produces:
  - `class RunQuotaError(RuntimeError)` in `manager.py`; `RunManager.create(kind, user_id: str | None = None)` writes `user_id` into the record; `RunManager.submit(kind, fn, *, singleton_key=None, user_id=None, max_concurrent: int | None = None)` counts the user's ACTIVE runs and raises `RunQuotaError` at the cap; `RunManager.list_active(user_id: str | None = None)` filters.
  - Runs router: submissions pass `user_id=ctx.user_id` and `max_concurrent=resolve_limit(user.max_concurrent_runs, system_default(..., DEFAULT_MAX_CONCURRENT_RUNS))`; `RunQuotaError` → `ApiException(429, "QUOTA_EXCEEDED", …)`; `GET /api/runs` and `GET /api/runs/{id}` scope to the caller's `user_id` in multi-user mode (a foreign run 404s).
  - Ingest: the batch loop function in `discovery/ingest.py` (the one building `IngestCounts`) gains `max_active_jobs: int | None = None`; when the workspace's non-archived job count reaches the cap, would-be inserts are counted as `quota_skipped` (new `IngestCounts` field, default 0) and skipped **before** `save_or_upgrade` (pre-checked via `find_existing` returning `None`); upgrades still apply. The pull service resolves the cap from context (same `resolve_limit` pattern) and reports `quota reached` in the run summary when `quota_skipped > 0`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_run_quota.py
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from resume_agent.api.runs.manager import RunManager, RunQuotaError


def test_submit_rejects_beyond_user_cap(tmp_path):
    manager = RunManager(root=tmp_path, executor=ThreadPoolExecutor(max_workers=4))
    release = threading.Event()

    def blocker(reporter):
        release.wait(timeout=10)
        return {}

    manager.submit("pull", blocker, user_id="u1", max_concurrent=2)
    manager.submit("tailor", blocker, user_id="u1", max_concurrent=2)
    with pytest.raises(RunQuotaError):
        manager.submit("discover", blocker, user_id="u1", max_concurrent=2)
    # a different user is unaffected
    manager.submit("pull", blocker, user_id="u2", max_concurrent=2)
    release.set()
    manager.shutdown()


def test_list_active_filters_by_user(tmp_path):
    manager = RunManager(root=tmp_path, executor=ThreadPoolExecutor(max_workers=4))
    release = threading.Event()

    def blocker(reporter):
        release.wait(timeout=10)
        return {}

    manager.submit("pull", blocker, user_id="u1", max_concurrent=5)
    manager.submit("pull", blocker, user_id="u2", max_concurrent=5)
    assert len(manager.list_active(user_id="u1")) == 1
    assert len(manager.list_active()) == 2
    release.set()
    manager.shutdown()
```

```python
# tests/test_ingest_job_cap.py
from sqlmodel import Session, select

from resume_agent.db import init_db, make_engine
from resume_agent.tracking.tables import Job

# Import the batch-ingest loop; check its actual name in discovery/ingest.py
# (the function that returns IngestCounts) and the RawJob constructor shape
# used by existing tests in tests/test_discovery_ingest.py — mirror them.
from resume_agent.discovery.ingest import ingest_raw_jobs  # adjust if named differently
from resume_agent.discovery.connectors.base import RawJob  # adjust import to match repo


def _raw(n):
    return RawJob(
        source="greenhouse", url=f"https://example.com/{n}",
        company=f"Co{n}", title=f"Engineer {n}", location="Remote",
        jd_text=f"JD {n}", posted_at=None,
    )


def test_cap_stops_inserts_but_not_upgrades(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'ws.db').as_posix()}")
    init_db(engine)
    with Session(engine) as session:
        counts = ingest_raw_jobs(session, [_raw(1), _raw(2), _raw(3)], max_active_jobs=2)
        assert sum(counts.added.values()) == 2
        assert counts.quota_skipped == 1
        assert len(session.exec(select(Job)).all()) == 2
    engine.dispose()
```

Adjust imports/constructor to the real shapes (see `tests/test_discovery_ingest.py` for the canonical way existing tests build `RawJob` and call the loop).

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_run_quota.py tests/test_ingest_job_cap.py -v`
Expected: FAIL — unexpected keyword arguments

- [ ] **Step 3: Implement the RunManager changes**

In `manager.py`:

```python
class RunQuotaError(RuntimeError):
    code = "QUOTA_EXCEEDED"
```

`create` gains `user_id: str | None = None` and writes `"user_id": user_id` into the seeded record. `list_active` gains `user_id: str | None = None` and filters `snapshot.user_id == user_id` when given (add `user_id: str | None = None` to `RunSnapshot` in `models.py` and carry it through `parse_run_snapshot` from the record). `submit` gains `user_id=None, max_concurrent=None` and, inside the `_singleton_lock` block before `create`:

```python
            if user_id is not None and max_concurrent is not None and max_concurrent > 0:
                active = [s for s in self.list_active() if s.user_id == user_id]
                if len(active) >= max_concurrent:
                    raise RunQuotaError(
                        f"{len(active)} runs already active (limit {max_concurrent})"
                    )
            run_id = self.create(kind, user_id=user_id)
```

- [ ] **Step 4: Implement the router + ingest changes**

In `api/routers/runs.py`, every `run_manager.submit(...)` call site passes `user_id` and cap resolved from the active context (no-op `None`s in legacy mode):

```python
from resume_agent.tenancy.context import current_context
from resume_agent.tenancy.limits import (
    DEFAULT_MAX_CONCURRENT_RUNS,
    resolve_limit,
    system_default,
)


def _quota_args(request) -> dict:
    ctx = current_context()
    if ctx is None or request.app.state.system_engine is None:
        return {}
    from sqlalchemy.orm import Session
    from resume_agent.tenancy.system_db import User

    with Session(request.app.state.system_engine) as session:
        user = session.get(User, ctx.user_id)
    cap = resolve_limit(
        user.max_concurrent_runs if user else None,
        system_default(
            request.app.state.system_engine,
            "max_concurrent_runs",
            DEFAULT_MAX_CONCURRENT_RUNS,
        ),
    )
    return {"user_id": ctx.user_id, "max_concurrent": cap}
```

wrap each submit in `try/except RunQuotaError` → `raise ApiException(429, "QUOTA_EXCEEDED", str(exc))`; and scope reads: in the list endpoint pass `user_id=ctx.user_id` when a context is active; in the single-run endpoint 404 when `snapshot.user_id` is set and differs from the caller's.

In `discovery/ingest.py`, extend the loop function (and `IngestCounts` with `quota_skipped: int = 0`):

```python
def ingest_raw_jobs(session, raw_jobs, *, max_active_jobs: int | None = None, ...):
    remaining: int | None = None
    if max_active_jobs is not None and max_active_jobs > 0:
        active = session.exec(
            select(func.count()).select_from(Job).where(Job.archived_at.is_(None))
        ).one()
        remaining = max(0, max_active_jobs - int(active))
    quota_skipped = 0
    for raw in raw_jobs:
        if remaining is not None and remaining == 0:
            incoming = IncomingJob.clean(source=raw.source, jd_text=raw.jd_text, url=raw.url,
                                         company=raw.company, title=raw.title, location=raw.location)
            if find_existing(session, incoming) is None:
                quota_skipped += 1
                continue  # would insert -> quota; existing rows still upgrade below
        job, outcome = save_or_upgrade(...)  # existing call
        if outcome is IngestOutcome.inserted and remaining is not None:
            remaining -= 1
        ...
    return IngestCounts(..., quota_skipped=quota_skipped)
```

Match the real loop's structure (this is a delta on the code at `discovery/ingest.py:140-187`); pass the cap from the pull service the same way `enforce_active_budget` resolves limits (context + `system_default(..., "max_active_jobs", DEFAULT_MAX_ACTIVE_JOBS)` + `User.max_active_jobs` override), and surface `quota_skipped > 0` as `quota reached` in the pull telemetry/summary.

- [ ] **Step 5: Contract regen + docs**

Run: `bash scripts/gen_ts_client.sh`
Run: `.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -v` → drift gate green

Append to CLAUDE.md's tenancy section:

```markdown
Budgets and quotas: usage is recorded in `llm_runner.acall` (best-effort,
never breaks the call); budgets are enforced per phase via
`tenancy/limits.enforce_active_budget()` (admins and own-key exempt);
`RunManager.submit` caps per-user concurrent runs (429 QUOTA_EXCEEDED);
the ingest loop caps non-archived jobs per workspace (inserts skip,
upgrades apply). NULL limit = system default, 0 = unlimited.
```

- [ ] **Step 6: Run the full suite**

Run: `.venv/Scripts/python.exe -m pytest -q && ruff check`
Expected: green

- [ ] **Step 7: Commit**

```bash
git add src/resume_agent/api/runs src/resume_agent/api/routers/runs.py src/resume_agent/discovery/ingest.py contracts CLAUDE.md tests/api/test_run_quota.py tests/test_ingest_job_cap.py
git commit -m "Adds per-user run and job quotas with 429 surfacing"
```
