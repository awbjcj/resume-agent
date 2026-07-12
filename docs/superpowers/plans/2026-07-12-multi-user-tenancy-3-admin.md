# Multi-User Tenancy — Plan 3: Admin Surfaces

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The management surfaces on top of Plans 1-2: an admin API (users, invites, system defaults, aggregate usage), self-service account endpoints (password change, workspace export), an HTTP-client admin CLI, and the SPA register/account/admin pages.

**Architecture:** One admin router guarded by a `require_admin` dependency layered over `get_user_context`. The admin CLI is a thin httpx client over exactly the same endpoints the SPA admin page calls (vsda's `manage_users.py` pattern): one surface, two clients. Self-service export reuses the existing whole-root archive mechanics scoped to one Workspace. Spec: `docs/superpowers/specs/2026-07-12-multi-user-tenancy-design.md` §5.

**Tech Stack:** Python 3.12, FastAPI, typer + httpx (CLI), React 18 + TypeScript (SPA, existing `web/` Vite app), pytest offline, vitest.

## Correctness amendments (audit before implementation)

These corrections are normative and override later reference snippets:

- Use the actual stack: Python **3.13+**, React **19**, React Router **7**, and
  the installed base-nova shadcn system. Build UI with the generated API
  client/React Query and existing components; the raw-fetch/bare-markup/
  `window.confirm` snippets are reference logic only.
- Admin schemas validate roles, password/token lengths, expiry ranges, and
  limits (`ge=0`). The user response includes `lastActiveAt`; auth updates it
  with a bounded cadence so the promised admin column is real.
- Deletion is failure-atomic: validate guards, evict the workspace engine,
  rename the Workspace to a quarantine path, delete/revoke user credentials in
  one system transaction, then remove the quarantine. Restore it on failure;
  never commit the user deletion first or hide `rmtree` failure with
  `ignore_errors=True`.
- Account usage applies the same rolling seven-day cutoff to shared-key and
  own-key totals. Export filenames use the validated username, and export
  tests assert no sibling/system files or traversal names are present.
- The sync `httpx.Client(ASGITransport(...))` test snippet is invalid in current
  httpx because ASGITransport is async-only. Test the CLI with a
  `TestClient`-backed client/protocol. Cache credentials atomically with
  owner-only permissions where supported, store the minted token id, and make
  `admin logout` revoke that PAT before removing local credentials when the
  server is reachable.
- Add TDD component tests before both Register and Account implementations,
  not only a single Account render test. Cover error/loading/empty states,
  one-time secret copy, password flow, responsive admin actions, accessible
  AlertDialog deletion, route-level admin denial, and nav gating.
- Whole-root export snapshots every SQLite database and omits WAL/SHM
  sidecars. Import closes each engine once, preserves rollback data on restore
  failure, rebuilds and validates the imported tenancy before returning 200,
  and does not rely on a process-global usage recorder.
- Contract regeneration and broad backend/web/browser verification occur once
  after all three plans; task-level checks remain the smallest RED/GREEN proof.

## Global Constraints

- **Strict TDD** (superpowers:test-driven-development): every task writes its failing test first and runs it to observe RED before any implementation code; implementation is the minimum to reach GREEN. Never reorder these steps (SPA tasks: component test before wiring the route).
- Prerequisites: Plans 1 and 2 fully landed (this plan consumes `mu_client`/`login` fixtures, `require_context`, the system tables, and `resolve_limit`/`system_default`).
- Delete-user refuses: the last admin, self-deletion, and targets with in-flight runs; it evicts the engine (`EngineRegistry.evict`) **before** removing the workspace directory; requires `?confirm=DELETE`.
- Self-service export contains the caller's `secrets.env` — the UI must say so ("this archive is secret material").
- PAT-based admin CLI: `admin login` = login endpoint → mint PAT named `cli` → cache `{apiUrl, username, token}` at `~/.resume-agent/credentials.json`; server chosen by `RESUME_AGENT_URL` (default `http://localhost:8000`).
- Non-admin on `/api/admin/*` → 403 `FORBIDDEN`. Admin page hidden from non-admin nav; register page linked from login.
- All new endpoints ride the contract pipeline: camelCase schemas → `bash scripts/gen_ts_client.sh` → drift gate `tests/api/test_openapi_contract.py`.
- Test: `.venv/Scripts/python.exe -m pytest`; lint: `ruff check`; web: `cd web && npx vitest run`.

---

### Task 1: `require_admin` + admin users API

**Files:**
- Create: `src/resume_agent/api/routers/admin_users.py`
- Create: `src/resume_agent/api/schemas/admin_users.py`
- Modify: `src/resume_agent/api/deps.py` (add `require_admin`)
- Modify: `src/resume_agent/api/app.py` (include router)
- Test: `tests/api/test_admin_users.py`

**Interfaces:**
- Consumes: `require_context` (Plan 1), `weekly_usage`/`resolve_limit`/`system_default` (Plan 2 `tenancy/limits.py`), `EngineRegistry.evict`, `hash_password`.
- Produces:
  - `require_admin()` dependency: `require_context()` + 403 `FORBIDDEN` unless `ctx.is_admin`.
  - `GET /api/admin/users` → `{users: [{id, username, role, disabledAt, createdAt, weeklyTokenBudget, maxActiveJobs, maxConcurrentRuns, weeklyUsage, activeJobs}]}`.
  - `PATCH /api/admin/users/{user_id}` body `{role?, weeklyTokenBudget?, maxActiveJobs?, maxConcurrentRuns?, disabled?}` (explicit-null semantics: fields absent = unchanged; `null` budget = revert to default).
  - `POST /api/admin/users/{user_id}/reset-password {password}` → sets a new hash (sessions die via the hash-fragment signature).
  - `DELETE /api/admin/users/{user_id}?confirm=DELETE` → refuses last admin (`409 LAST_ADMIN`), self (`409 SELF_DELETE`), in-flight runs (`409 RUNS_ACTIVE`); evicts engine, removes `users/<id>/`, deletes the row.

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_admin_users.py
from sqlalchemy.orm import Session

from resume_agent.tenancy.system_db import User

from tests.api.conftest import login
from tests.api.test_tenancy_isolation import _register


def test_non_admin_gets_403(mu_app, mu_client):
    _register(mu_app, mu_client, "alice")
    login(mu_client, "alice", "pw")
    response = mu_client.get("/api/admin/users")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_list_users_with_usage_and_limits(mu_app, mu_client):
    _register(mu_app, mu_client, "alice")
    login(mu_client)
    body = mu_client.get("/api/admin/users").json()
    names = {u["username"]: u for u in body["users"]}
    assert set(names) == {"owner", "alice"}
    assert names["owner"]["role"] == "admin"
    assert names["alice"]["weeklyUsage"] == 0
    assert names["alice"]["weeklyTokenBudget"] is None  # NULL = default


def test_patch_role_and_limits(mu_app, mu_client):
    _register(mu_app, mu_client, "alice")
    login(mu_client)
    with Session(mu_app.state.system_engine) as session:
        alice_id = session.query(User).filter_by(username="alice").one().id
    response = mu_client.patch(
        f"/api/admin/users/{alice_id}",
        json={"role": "admin", "weeklyTokenBudget": 5000000, "disabled": True},
    )
    assert response.status_code == 200
    with Session(mu_app.state.system_engine) as session:
        row = session.get(User, alice_id)
        assert row.role == "admin"
        assert row.weekly_token_budget == 5000000
        assert row.disabled_at is not None


def test_disabled_user_cannot_login(mu_app, mu_client):
    _register(mu_app, mu_client, "alice")
    login(mu_client)
    with Session(mu_app.state.system_engine) as session:
        alice_id = session.query(User).filter_by(username="alice").one().id
    mu_client.patch(f"/api/admin/users/{alice_id}", json={"disabled": True})
    mu_client.cookies.clear()
    response = mu_client.post("/api/auth/login", json={"username": "alice", "password": "pw"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "USER_DISABLED"


def test_reset_password(mu_app, mu_client):
    _register(mu_app, mu_client, "alice")
    login(mu_client)
    with Session(mu_app.state.system_engine) as session:
        alice_id = session.query(User).filter_by(username="alice").one().id
    assert mu_client.post(
        f"/api/admin/users/{alice_id}/reset-password", json={"password": "newpw"}
    ).status_code == 200
    mu_client.cookies.clear()
    assert mu_client.post(
        "/api/auth/login", json={"username": "alice", "password": "newpw"}
    ).status_code == 200


def test_delete_guards_and_success(mu_app, mu_client):
    _register(mu_app, mu_client, "alice")
    login(mu_client)
    with Session(mu_app.state.system_engine) as session:
        users = {u.username: u.id for u in session.query(User).all()}

    assert mu_client.delete(f"/api/admin/users/{users['alice']}").status_code == 400  # no confirm
    assert mu_client.delete(
        f"/api/admin/users/{users['owner']}?confirm=DELETE"
    ).json()["error"]["code"] == "SELF_DELETE"

    alice_ws = mu_app.state.data_dir / "users" / users["alice"]
    assert alice_ws.is_dir()
    assert mu_client.delete(f"/api/admin/users/{users['alice']}?confirm=DELETE").status_code == 200
    assert not alice_ws.exists()
    with Session(mu_app.state.system_engine) as session:
        assert session.get(User, users["alice"]) is None

    # owner is now the last admin
    assert mu_client.delete(
        f"/api/admin/users/{users['owner']}?confirm=DELETE"
    ).json()["error"]["code"] == "SELF_DELETE"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_admin_users.py -v`
Expected: FAIL — 404s (router missing). Note `test_disabled_user_cannot_login` also exercises Plan 2's login path.

- [ ] **Step 3: Implement**

`require_admin` in `deps.py`:

```python
def require_admin() -> UserContext:
    from resume_agent.tenancy.context import require_context

    ctx = require_context()
    if not ctx.is_admin:
        raise ApiException(403, "FORBIDDEN", "Admin role required")
    return ctx
```

```python
# src/resume_agent/api/schemas/admin_users.py
from datetime import datetime

from pydantic import Field

from resume_agent.api.schemas.base import CamelModel


class AdminUser(CamelModel):
    id: str
    username: str
    role: str
    created_at: datetime
    disabled_at: datetime | None = None
    weekly_token_budget: int | None = None
    max_active_jobs: int | None = None
    max_concurrent_runs: int | None = None
    weekly_usage: float = 0.0
    active_jobs: int = 0


class AdminUserList(CamelModel):
    users: list[AdminUser]


_UNSET = object()


class AdminUserPatch(CamelModel):
    role: str | None = None
    disabled: bool | None = None
    # Use Field(default=None) + model_fields_set to distinguish "absent" from null
    weekly_token_budget: int | None = Field(default=None)
    max_active_jobs: int | None = Field(default=None)
    max_concurrent_runs: int | None = Field(default=None)


class ResetPasswordRequest(CamelModel):
    password: str
```

```python
# src/resume_agent/api/routers/admin_users.py
"""Admin user management — the one surface behind both the SPA admin page
and the HTTP-client admin CLI."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlmodel import Session as SMSession
from sqlmodel import select as sm_select

from resume_agent.api import auth
from resume_agent.api.deps import require_admin
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.admin_users import (
    AdminUser,
    AdminUserList,
    AdminUserPatch,
    ResetPasswordRequest,
)
from resume_agent.tenancy.context import UserContext
from resume_agent.tenancy.limits import weekly_usage
from resume_agent.tenancy.system_db import User
from resume_agent.tenancy.workspace import workspace_paths
from resume_agent.tracking.tables import Job

router = APIRouter(prefix="/admin/users", tags=["admin"])


def _system_engine(request: Request):
    engine = request.app.state.system_engine
    if engine is None:
        raise ApiException(400, "AUTH_NOT_CONFIGURED", "Admin API requires multi-user mode")
    return engine


def _active_jobs(request: Request, user: User) -> int:
    registry = request.app.state.engine_registry
    ws = workspace_paths(request.app.state.data_dir, user.id)
    if not ws.db_file.is_file():
        return 0
    engine = registry.get(user.id, ws.db_url)
    with SMSession(engine) as session:
        return int(
            session.exec(
                sm_select(func.count()).select_from(Job).where(Job.archived_at.is_(None))
            ).one()
        )


@router.get("")
def list_users(
    request: Request, ctx: UserContext = Depends(require_admin)
) -> AdminUserList:
    engine = _system_engine(request)
    with Session(engine) as session:
        rows = session.execute(select(User).order_by(User.created_at)).scalars().all()
        users = [
            AdminUser(
                id=row.id,
                username=row.username,
                role=row.role,
                created_at=row.created_at,
                disabled_at=row.disabled_at,
                weekly_token_budget=row.weekly_token_budget,
                max_active_jobs=row.max_active_jobs,
                max_concurrent_runs=row.max_concurrent_runs,
                weekly_usage=weekly_usage(engine, row.id),
                active_jobs=_active_jobs(request, row),
            )
            for row in rows
        ]
    return AdminUserList(users=users)


@router.patch("/{user_id}")
def patch_user(
    user_id: str,
    body: AdminUserPatch,
    request: Request,
    ctx: UserContext = Depends(require_admin),
) -> dict[str, str]:
    engine = _system_engine(request)
    with Session(engine) as session:
        user = session.get(User, user_id)
        if user is None:
            raise ApiException(404, "NOT_FOUND", "No such user")
        provided = body.model_fields_set
        if body.role is not None:
            if body.role not in {"admin", "user"}:
                raise ApiException(400, "VALIDATION", "role must be 'admin' or 'user'")
            if user.role == "admin" and body.role != "admin" and _last_admin(session, user):
                raise ApiException(409, "LAST_ADMIN", "Cannot demote the last admin")
            user.role = body.role
        if body.disabled is not None:
            if body.disabled and user.id == ctx.user_id:
                raise ApiException(409, "SELF_DELETE", "Cannot disable yourself")
            user.disabled_at = datetime.now(timezone.utc) if body.disabled else None
        for field in ("weekly_token_budget", "max_active_jobs", "max_concurrent_runs"):
            if field in provided:
                setattr(user, field, getattr(body, field))
        session.commit()
    return {"status": "updated"}


def _last_admin(session: Session, user: User) -> bool:
    admins = session.execute(
        select(func.count()).select_from(User).where(
            User.role == "admin", User.disabled_at.is_(None)
        )
    ).scalar_one()
    return int(admins) <= 1


@router.post("/{user_id}/reset-password")
def reset_password(
    user_id: str,
    body: ResetPasswordRequest,
    request: Request,
    ctx: UserContext = Depends(require_admin),
) -> dict[str, str]:
    engine = _system_engine(request)
    with Session(engine) as session:
        user = session.get(User, user_id)
        if user is None:
            raise ApiException(404, "NOT_FOUND", "No such user")
        user.password_hash = auth.hash_password(body.password)
        session.commit()
    return {"status": "reset"}


@router.delete("/{user_id}")
def delete_user(
    user_id: str,
    request: Request,
    confirm: str = "",
    ctx: UserContext = Depends(require_admin),
) -> dict[str, str]:
    if confirm != "DELETE":
        raise ApiException(400, "CONFIRM_REQUIRED", "Deleting removes the workspace; pass ?confirm=DELETE")
    if user_id == ctx.user_id:
        raise ApiException(409, "SELF_DELETE", "Cannot delete yourself")
    engine = _system_engine(request)
    active = request.app.state.run_manager.list_active(user_id=user_id)
    if active:
        raise ApiException(409, "RUNS_ACTIVE", "Refusing while the user has active runs")
    with Session(engine) as session:
        user = session.get(User, user_id)
        if user is None:
            raise ApiException(404, "NOT_FOUND", "No such user")
        if user.role == "admin" and _last_admin(session, user):
            raise ApiException(409, "LAST_ADMIN", "Cannot delete the last admin")
        session.delete(user)
        session.commit()
    # Evict BEFORE removing the directory: open SQLite handles block
    # directory removal on Windows.
    request.app.state.engine_registry.evict(user_id)
    workspace = workspace_paths(request.app.state.data_dir, user_id).root
    shutil.rmtree(workspace, ignore_errors=True)
    return {"status": "deleted"}
```

Register in `app.py`: `from resume_agent.api.routers import admin_users as admin_users_router` and `app.include_router(admin_users_router.router, prefix="/api", dependencies=guarded)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_admin_users.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/api/routers/admin_users.py src/resume_agent/api/schemas/admin_users.py src/resume_agent/api/deps.py src/resume_agent/api/app.py tests/api/test_admin_users.py
git commit -m "Adds admin user management API with guarded deletion"
```

---

### Task 2: Invites API

**Files:**
- Create: `src/resume_agent/api/routers/admin_invites.py`
- Create: `src/resume_agent/api/schemas/admin_invites.py`
- Modify: `src/resume_agent/api/app.py` (include router)
- Test: `tests/api/test_admin_invites.py`

**Interfaces:**
- Produces:
  - `POST /api/admin/invites {expiresInDays?: int = 14}` → `{id, code, expiresAt}` (raw `inv_…` shown once).
  - `GET /api/admin/invites` → `{invites: [{id, createdBy, createdAt, expiresAt, usedBy, usedAt, revokedAt}]}` (no hashes).
  - `DELETE /api/admin/invites/{invite_id}` → sets `revoked_at` (revoking a used invite 409s).

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_admin_invites.py
from tests.api.conftest import login


def test_mint_list_revoke_invite(mu_client):
    login(mu_client)
    minted = mu_client.post("/api/admin/invites", json={"expiresInDays": 7})
    assert minted.status_code == 200
    body = minted.json()
    assert body["code"].startswith("inv_")

    listed = mu_client.get("/api/admin/invites").json()["invites"]
    assert len(listed) == 1
    assert "code" not in listed[0] and "codeHash" not in listed[0]

    assert mu_client.delete(f"/api/admin/invites/{body['id']}").status_code == 200
    # a revoked code cannot register
    response = mu_client.post(
        "/api/auth/register",
        json={"username": "x", "password": "p", "inviteCode": body["code"]},
    )
    assert response.json()["error"]["code"] == "INVITE_INVALID"


def test_used_invite_cannot_be_revoked(mu_app, mu_client):
    login(mu_client)
    code = mu_client.post("/api/admin/invites", json={}).json()
    ok = mu_client.post(
        "/api/auth/register",
        json={"username": "alice", "password": "pw", "inviteCode": code["code"]},
    )
    assert ok.status_code == 200
    login(mu_client)  # register does not log in; re-auth as admin
    assert mu_client.delete(f"/api/admin/invites/{code['id']}").status_code == 409
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_admin_invites.py -v`
Expected: FAIL — 404s

- [ ] **Step 3: Implement**

```python
# src/resume_agent/api/schemas/admin_invites.py
from datetime import datetime

from resume_agent.api.schemas.base import CamelModel


class InviteMintRequest(CamelModel):
    expires_in_days: int = 14


class InviteMinted(CamelModel):
    id: str
    code: str  # raw secret — shown exactly once
    expires_at: datetime


class InviteInfo(CamelModel):
    id: str
    created_by: str
    created_at: datetime
    expires_at: datetime
    used_by: str | None = None
    used_at: datetime | None = None
    revoked_at: datetime | None = None


class InviteList(CamelModel):
    invites: list[InviteInfo]
```

```python
# src/resume_agent/api/routers/admin_invites.py
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from resume_agent.api.deps import require_admin
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.admin_invites import (
    InviteInfo,
    InviteList,
    InviteMinted,
    InviteMintRequest,
)
from resume_agent.tenancy.context import UserContext
from resume_agent.tenancy.secrets import hash_secret, mint_secret
from resume_agent.tenancy.system_db import InviteCode

router = APIRouter(prefix="/admin/invites", tags=["admin"])


@router.post("")
def mint_invite(
    body: InviteMintRequest,
    request: Request,
    ctx: UserContext = Depends(require_admin),
) -> InviteMinted:
    if not 1 <= body.expires_in_days <= 365:
        raise ApiException(400, "VALIDATION", "expiresInDays must be 1..365")
    raw = mint_secret("inv_")
    row = InviteCode(
        id=uuid.uuid4().hex[:12],
        code_hash=hash_secret(raw),
        created_by=ctx.user_id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=body.expires_in_days),
    )
    with Session(request.app.state.system_engine) as session:
        session.add(row)
        session.commit()
        return InviteMinted(id=row.id, code=raw, expires_at=row.expires_at)


@router.get("")
def list_invites(
    request: Request, ctx: UserContext = Depends(require_admin)
) -> InviteList:
    with Session(request.app.state.system_engine) as session:
        rows = session.execute(
            select(InviteCode).order_by(InviteCode.created_at.desc())
        ).scalars().all()
        return InviteList(invites=[InviteInfo.model_validate(row) for row in rows])


@router.delete("/{invite_id}")
def revoke_invite(
    invite_id: str, request: Request, ctx: UserContext = Depends(require_admin)
) -> dict[str, str]:
    with Session(request.app.state.system_engine) as session:
        row = session.get(InviteCode, invite_id)
        if row is None:
            raise ApiException(404, "NOT_FOUND", "No such invite")
        if row.used_at is not None:
            raise ApiException(409, "INVITE_USED", "Invite already consumed")
        row.revoked_at = datetime.now(timezone.utc)
        session.commit()
    return {"status": "revoked"}
```

Register in `app.py` with the guarded dependency list.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_admin_invites.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/api/routers/admin_invites.py src/resume_agent/api/schemas/admin_invites.py src/resume_agent/api/app.py tests/api/test_admin_invites.py
git commit -m "Adds invite minting, listing, and revocation"
```

---

### Task 3: System defaults + aggregate usage

**Files:**
- Create: `src/resume_agent/api/routers/admin_system.py`
- Create: `src/resume_agent/api/schemas/admin_system.py`
- Modify: `src/resume_agent/api/app.py`
- Test: `tests/api/test_admin_system.py`

**Interfaces:**
- Produces:
  - `GET /api/admin/system/defaults` → `{weeklyTokenBudget, maxActiveJobs, maxConcurrentRuns}` (resolved: stored `SystemSetting` or shipped default).
  - `PUT /api/admin/system/defaults` same shape → upserts `SystemSetting` rows.
  - `GET /api/admin/system/usage?days=7` → `{users: [{userId, username, weightedTotal, ownKeyWeightedTotal, calls}]}` aggregated from `UsageEvent`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_admin_system.py
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from resume_agent.tenancy.limits import DEFAULT_WEEKLY_TOKEN_BUDGET
from resume_agent.tenancy.system_db import UsageEvent, User

from tests.api.conftest import login


def test_defaults_roundtrip(mu_client):
    login(mu_client)
    initial = mu_client.get("/api/admin/system/defaults").json()
    assert initial["weeklyTokenBudget"] == DEFAULT_WEEKLY_TOKEN_BUDGET
    updated = mu_client.put(
        "/api/admin/system/defaults",
        json={"weeklyTokenBudget": 5000000, "maxActiveJobs": 500, "maxConcurrentRuns": 1},
    )
    assert updated.status_code == 200
    assert mu_client.get("/api/admin/system/defaults").json()["weeklyTokenBudget"] == 5000000


def test_aggregate_usage(mu_app, mu_client):
    login(mu_client)
    with Session(mu_app.state.system_engine) as session:
        owner = session.query(User).filter_by(username="owner").one()
        session.add(UsageEvent(
            user_id=owner.id, ts=datetime.now(timezone.utc),
            weighted_total=100.0, own_key=False,
        ))
        session.add(UsageEvent(
            user_id=owner.id, ts=datetime.now(timezone.utc),
            weighted_total=40.0, own_key=True,
        ))
        session.commit()
    body = mu_client.get("/api/admin/system/usage").json()
    row = next(u for u in body["users"] if u["username"] == "owner")
    assert row["weightedTotal"] == 100.0
    assert row["ownKeyWeightedTotal"] == 40.0
    assert row["calls"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_admin_system.py -v`
Expected: FAIL — 404s

- [ ] **Step 3: Implement**

```python
# src/resume_agent/api/schemas/admin_system.py
from resume_agent.api.schemas.base import CamelModel


class SystemDefaults(CamelModel):
    weekly_token_budget: int
    max_active_jobs: int
    max_concurrent_runs: int


class UserUsage(CamelModel):
    user_id: str
    username: str
    weighted_total: float
    own_key_weighted_total: float
    calls: int


class UsageReport(CamelModel):
    users: list[UserUsage]
```

```python
# src/resume_agent/api/routers/admin_system.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from resume_agent.api.deps import require_admin
from resume_agent.api.schemas.admin_system import SystemDefaults, UsageReport, UserUsage
from resume_agent.tenancy.context import UserContext
from resume_agent.tenancy.limits import (
    DEFAULT_MAX_ACTIVE_JOBS,
    DEFAULT_MAX_CONCURRENT_RUNS,
    DEFAULT_WEEKLY_TOKEN_BUDGET,
    system_default,
)
from resume_agent.tenancy.system_db import SystemSetting, UsageEvent, User

router = APIRouter(prefix="/admin/system", tags=["admin"])

_DEFAULT_KEYS = {
    "weekly_token_budget": DEFAULT_WEEKLY_TOKEN_BUDGET,
    "max_active_jobs": DEFAULT_MAX_ACTIVE_JOBS,
    "max_concurrent_runs": DEFAULT_MAX_CONCURRENT_RUNS,
}


@router.get("/defaults")
def get_defaults(
    request: Request, ctx: UserContext = Depends(require_admin)
) -> SystemDefaults:
    engine = request.app.state.system_engine
    return SystemDefaults(**{
        key: system_default(engine, key, fallback)
        for key, fallback in _DEFAULT_KEYS.items()
    })


@router.put("/defaults")
def put_defaults(
    body: SystemDefaults, request: Request, ctx: UserContext = Depends(require_admin)
) -> SystemDefaults:
    with Session(request.app.state.system_engine) as session:
        for key in _DEFAULT_KEYS:
            value = str(getattr(body, key))
            row = session.get(SystemSetting, key)
            if row is None:
                session.add(SystemSetting(key=key, value=value))
            else:
                row.value = value
        session.commit()
    return body


@router.get("/usage")
def usage_report(
    request: Request, days: int = 7, ctx: UserContext = Depends(require_admin)
) -> UsageReport:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 90)))
    with Session(request.app.state.system_engine) as session:
        rows = session.execute(
            select(
                UsageEvent.user_id,
                func.coalesce(User.username, UsageEvent.user_id),
                func.coalesce(
                    func.sum(case((UsageEvent.own_key.is_(False), UsageEvent.weighted_total), else_=0.0)), 0.0
                ),
                func.coalesce(
                    func.sum(case((UsageEvent.own_key.is_(True), UsageEvent.weighted_total), else_=0.0)), 0.0
                ),
                func.count(UsageEvent.id),
            )
            .outerjoin(User, User.id == UsageEvent.user_id)
            .where(UsageEvent.ts >= cutoff)
            .group_by(UsageEvent.user_id)
        ).all()
    return UsageReport(users=[
        UserUsage(
            user_id=r[0], username=r[1], weighted_total=float(r[2]),
            own_key_weighted_total=float(r[3]), calls=int(r[4]),
        )
        for r in rows
    ])
```

Register in `app.py` with the guarded list.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_admin_system.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/api/routers/admin_system.py src/resume_agent/api/schemas/admin_system.py src/resume_agent/api/app.py tests/api/test_admin_system.py
git commit -m "Adds system defaults and aggregate usage endpoints"
```

---

### Task 4: Account endpoints — change password + self-service export

**Files:**
- Modify: `src/resume_agent/api/routers/account.py` (from Plan 2 Task 5)
- Modify: `src/resume_agent/api/schemas/account.py`
- Test: `tests/api/test_account.py`

**Interfaces:**
- Produces:
  - `POST /api/account/password {currentPassword, newPassword}` — verifies current, sets new hash; the response also sets a **fresh session cookie** (the old signature just died with the hash change).
  - `GET /api/account/export` → `tar.gz` of the caller's own Workspace, filename `workspace-<username>-<date>.tar.gz`. Reuses `services/backup.export_data_root(ws.root, ws.db_url, tmp)` — a Workspace is shaped like a data root (DB + dirs), so the WAL-safe snapshot logic applies unchanged. Refuses while the caller has active runs (`409 RUNS_ACTIVE`) — same reason as the admin export.
  - `GET /api/account/usage` → `{weightedTotal, budget, ownKeyWeightedTotal}` for the caller's rolling week (powers the account-page meter).

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_account.py
import io
import tarfile

from tests.api.conftest import login


def test_change_password_and_relogin(mu_client):
    login(mu_client)
    response = mu_client.post(
        "/api/account/password",
        json={"currentPassword": "pw", "newPassword": "pw2"},
    )
    assert response.status_code == 200
    mu_client.cookies.clear()
    assert mu_client.post(
        "/api/auth/login", json={"username": "owner", "password": "pw2"}
    ).status_code == 200
    assert mu_client.post(
        "/api/auth/login", json={"username": "owner", "password": "pw"}
    ).status_code == 401


def test_change_password_requires_current(mu_client):
    login(mu_client)
    assert mu_client.post(
        "/api/account/password",
        json={"currentPassword": "wrong", "newPassword": "pw2"},
    ).status_code == 401


def test_export_own_workspace_only(mu_app, mu_client):
    login(mu_client)
    response = mu_client.get("/api/account/export")
    assert response.status_code == 200
    archive = tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz")
    names = archive.getnames()
    assert not any("users/" in name for name in names)  # scoped to ONE workspace
    assert any(name.endswith("config") or "config" in name for name in names)


def test_account_usage_meter(mu_client):
    login(mu_client)
    body = mu_client.get("/api/account/usage").json()
    assert body["weightedTotal"] == 0.0
    assert body["budget"] > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_account.py -v`
Expected: FAIL — 404s

- [ ] **Step 3: Implement**

Schemas — append to `api/schemas/account.py`:

```python
class PasswordChangeRequest(CamelModel):
    current_password: str
    new_password: str


class AccountUsage(CamelModel):
    weighted_total: float
    own_key_weighted_total: float
    budget: int
```

Append to `api/routers/account.py`:

```python
import shutil
import tempfile
from datetime import date
from pathlib import Path

from fastapi import Depends, Response
from fastapi.responses import FileResponse
from sqlalchemy import case, func, select
from starlette.background import BackgroundTask

from resume_agent.api import auth as auth_mod
from resume_agent.api.deps import get_settings_dep
from resume_agent.api.schemas.account import AccountUsage, PasswordChangeRequest
from resume_agent.config import Settings
from resume_agent.services.backup import export_data_root
from resume_agent.tenancy.limits import (
    DEFAULT_WEEKLY_TOKEN_BUDGET,
    resolve_limit,
    system_default,
    weekly_usage,
)
from resume_agent.tenancy.system_db import UsageEvent, User
from resume_agent.tenancy.workspace import workspace_paths


@router.post("/password")
def change_password(
    body: PasswordChangeRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, str]:
    ctx = require_context()
    with Session(request.app.state.system_engine) as session:
        user = session.get(User, ctx.user_id)
        if user is None or not auth_mod.verify_password(
            body.current_password, user.password_hash
        ):
            raise ApiException(401, "UNAUTHORIZED", "Current password is incorrect")
        user.password_hash = auth_mod.hash_password(body.new_password)
        session.commit()
        new_hash = user.password_hash
    # The old sessions just died (hash fragment in the signature); keep THIS
    # session alive by reissuing against the new hash.
    token = auth_mod.issue_user_session(
        request.app.state.settings, user_id=ctx.user_id, password_hash=new_hash
    )
    response.set_cookie(
        auth_mod.SESSION_COOKIE, token,
        max_age=auth_mod.SESSION_LIFETIME_SECONDS,
        httponly=True, secure=True, samesite="lax", path="/",
    )
    return {"status": "changed"}


@router.get("/export")
def export_workspace(request: Request) -> FileResponse:
    ctx = require_context()
    if request.app.state.run_manager.list_active(user_id=ctx.user_id):
        raise ApiException(409, "RUNS_ACTIVE", "Refusing while your runs are active")
    ws = workspace_paths(request.app.state.data_dir, ctx.user_id)
    temporary = Path(tempfile.mkdtemp(prefix="ra-ws-export-"))
    try:
        archive = export_data_root(ws.root, ws.db_url, temporary)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    filename = f"workspace-{ctx.username}-{date.today().isoformat()}.tar.gz"
    return FileResponse(
        archive,
        media_type="application/gzip",
        filename=filename,
        background=BackgroundTask(shutil.rmtree, temporary, ignore_errors=True),
    )


@router.get("/usage")
def account_usage(request: Request) -> AccountUsage:
    ctx = require_context()
    engine = request.app.state.system_engine
    with Session(engine) as session:
        user = session.get(User, ctx.user_id)
        own_key_total = session.execute(
            select(func.coalesce(func.sum(
                case((UsageEvent.own_key.is_(True), UsageEvent.weighted_total), else_=0.0)
            ), 0.0)).where(UsageEvent.user_id == ctx.user_id)
        ).scalar_one()
    budget = resolve_limit(
        user.weekly_token_budget if user else None,
        system_default(engine, "weekly_token_budget", DEFAULT_WEEKLY_TOKEN_BUDGET),
    )
    return AccountUsage(
        weighted_total=weekly_usage(engine, ctx.user_id),
        own_key_weighted_total=float(own_key_total),
        budget=budget,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_account.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/api/routers/account.py src/resume_agent/api/schemas/account.py tests/api/test_account.py
git commit -m "Adds password change, workspace self-export, and usage meter"
```

---

### Task 5: Admin CLI — HTTP client

**Files:**
- Create: `src/resume_agent/admin_cli.py`
- Modify: `src/resume_agent/cli.py` (register the sub-app)
- Test: `tests/test_admin_cli.py`

**Interfaces:**
- Consumes: Tasks 1-4 endpoints; Plan 2 login + PAT endpoints.
- Produces: `resume-agent admin <cmd>` — `login`, `logout`, `whoami`, `list-users`, `invite [--expires-days N]`, `set-role USERNAME ROLE`, `set-limits USERNAME [--budget N] [--max-jobs N] [--max-runs N]`, `usage [--days N]`, `disable USERNAME`, `enable USERNAME`, `delete USERNAME --confirm`, `reset-password USERNAME`. Server from `RESUME_AGENT_URL` (default `http://localhost:8000`); credentials at `~/.resume-agent/credentials.json` (`{"apiUrl", "username", "token"}`, the token being a PAT named `cli`). All commands print human-readable tables/lines via `typer.echo`.

- [ ] **Step 1: Write the failing tests**

Test through the FastAPI app with httpx's ASGI transport so no server is needed:

```python
# tests/test_admin_cli.py
import httpx
import pytest

from resume_agent import admin_cli

from tests.api.conftest import login  # reuse fixture helpers; mu_app fixture via conftest


@pytest.fixture
def client_factory(mu_app, tmp_path, monkeypatch):
    """Route the admin CLI's HTTP at the in-process app and isolate its
    credentials file under tmp_path."""
    monkeypatch.setattr(admin_cli, "CREDENTIALS_PATH", tmp_path / "credentials.json")
    transport = httpx.ASGITransport(app=mu_app)

    def make(**kwargs):
        return httpx.Client(transport=transport, base_url="http://testserver", **kwargs)

    monkeypatch.setattr(admin_cli, "_make_client", lambda base_url: make())
    return make


def test_login_caches_pat(mu_app, mu_client, client_factory):
    admin_cli.do_login("http://testserver", "owner", "pw")
    creds = admin_cli.load_credentials()
    assert creds is not None
    assert creds["username"] == "owner"
    assert creds["token"].startswith("rat_")


def test_list_users_and_invite(mu_app, mu_client, client_factory, capsys):
    admin_cli.do_login("http://testserver", "owner", "pw")
    admin_cli.do_list_users()
    out = capsys.readouterr().out
    assert "owner" in out and "admin" in out

    admin_cli.do_invite(expires_days=7)
    out = capsys.readouterr().out
    assert "inv_" in out


def test_set_role_by_username(mu_app, mu_client, client_factory, capsys):
    admin_cli.do_login("http://testserver", "owner", "pw")
    admin_cli.do_invite(expires_days=7)
    code = capsys.readouterr().out.strip().split()[-1]
    with client_factory() as c:
        c.post("/api/auth/register", json={"username": "alice", "password": "pw", "inviteCode": code})
    admin_cli.do_set_role("alice", "admin")
    admin_cli.do_list_users()
    out = capsys.readouterr().out
    assert out.count("admin") >= 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_admin_cli.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement**

```python
# src/resume_agent/admin_cli.py
"""HTTP-client admin CLI (the vsda manage_users.py pattern).

Thin: every command is one or two HTTP calls against the same /api/admin/*
endpoints the SPA admin page uses. Auth: `admin login` exchanges
username/password for a session, mints a PAT named 'cli', and caches it.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import typer

CREDENTIALS_PATH = Path.home() / ".resume-agent" / "credentials.json"
DEFAULT_URL = "http://localhost:8000"

admin_app = typer.Typer(help="Manage users on a deployed resume-agent instance.")


def api_url() -> str:
    return os.environ.get("RESUME_AGENT_URL", DEFAULT_URL).rstrip("/")


def _make_client(base_url: str) -> httpx.Client:
    return httpx.Client(base_url=base_url, timeout=30.0)


def load_credentials() -> dict | None:
    try:
        return json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _save_credentials(creds: dict) -> None:
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_PATH.write_text(json.dumps(creds, indent=2), encoding="utf-8")


def _authed_client() -> httpx.Client:
    creds = load_credentials()
    if creds is None:
        raise typer.Exit(code=_fail("Not logged in. Run: resume-agent admin login"))
    client = _make_client(creds["apiUrl"])
    client.headers["Authorization"] = f"Bearer {creds['token']}"
    return client


def _fail(message: str) -> int:
    typer.echo(f"error: {message}", err=True)
    return 1


def _check(response: httpx.Response) -> dict:
    if response.status_code >= 400:
        try:
            detail = response.json()["error"]
            raise typer.Exit(code=_fail(f"{detail['code']}: {detail['message']}"))
        except (KeyError, ValueError):
            raise typer.Exit(code=_fail(f"HTTP {response.status_code}"))
    return response.json() if response.content else {}


def _resolve_user_id(client: httpx.Client, username: str) -> str:
    users = _check(client.get("/api/admin/users"))["users"]
    for user in users:
        if user["username"] == username or user["id"] == username:
            return user["id"]
    raise typer.Exit(code=_fail(f"user {username!r} not found"))


# ---- command bodies (testable without typer's runner) ----

def do_login(url: str, username: str, password: str) -> None:
    with _make_client(url) as client:
        _check(client.post("/api/auth/login", json={"username": username, "password": password}))
        minted = _check(client.post("/api/account/tokens", json={"name": "cli"}))
    _save_credentials({"apiUrl": url, "username": username, "token": minted["token"]})
    typer.echo(f"Logged in as {username} at {url}")


def do_logout() -> None:
    CREDENTIALS_PATH.unlink(missing_ok=True)
    typer.echo("Logged out.")


def do_whoami() -> None:
    creds = load_credentials()
    if creds is None:
        typer.echo(f"Not logged in. RESUME_AGENT_URL={api_url()}")
        return
    typer.echo(f"{creds['username']} -> {creds['apiUrl']}")


def do_list_users() -> None:
    with _authed_client() as client:
        users = _check(client.get("/api/admin/users"))["users"]
    header = f"{'USERNAME':<20}{'ROLE':<8}{'USAGE(7d)':>12}{'JOBS':>7}  LIMITS(budget/jobs/runs)"
    typer.echo(header)
    for user in users:
        flags = " [disabled]" if user["disabledAt"] else ""
        limits = "/".join(
            "default" if user[k] is None else str(user[k])
            for k in ("weeklyTokenBudget", "maxActiveJobs", "maxConcurrentRuns")
        )
        typer.echo(
            f"{user['username']:<20}{user['role']:<8}"
            f"{user['weeklyUsage']:>12,.0f}{user['activeJobs']:>7}  {limits}{flags}"
        )


def do_invite(expires_days: int = 14) -> None:
    with _authed_client() as client:
        minted = _check(client.post("/api/admin/invites", json={"expiresInDays": expires_days}))
    typer.echo(f"Invite (expires {minted['expiresAt']}): {minted['code']}")


def do_set_role(username: str, role: str) -> None:
    with _authed_client() as client:
        user_id = _resolve_user_id(client, username)
        _check(client.patch(f"/api/admin/users/{user_id}", json={"role": role}))
    typer.echo(f"{username} is now {role}")


def do_set_limits(
    username: str,
    budget: int | None = None,
    max_jobs: int | None = None,
    max_runs: int | None = None,
) -> None:
    payload: dict = {}
    if budget is not None:
        payload["weeklyTokenBudget"] = budget
    if max_jobs is not None:
        payload["maxActiveJobs"] = max_jobs
    if max_runs is not None:
        payload["maxConcurrentRuns"] = max_runs
    if not payload:
        raise typer.Exit(code=_fail("nothing to set"))
    with _authed_client() as client:
        user_id = _resolve_user_id(client, username)
        _check(client.patch(f"/api/admin/users/{user_id}", json=payload))
    typer.echo(f"Updated limits for {username}")


def do_usage(days: int = 7) -> None:
    with _authed_client() as client:
        report = _check(client.get(f"/api/admin/system/usage?days={days}"))
    for row in report["users"]:
        typer.echo(
            f"{row['username']:<20}{row['weightedTotal']:>14,.0f}"
            f"  (own-key {row['ownKeyWeightedTotal']:,.0f}, {row['calls']} calls)"
        )


def do_set_disabled(username: str, disabled: bool) -> None:
    with _authed_client() as client:
        user_id = _resolve_user_id(client, username)
        _check(client.patch(f"/api/admin/users/{user_id}", json={"disabled": disabled}))
    typer.echo(f"{'Disabled' if disabled else 'Enabled'} {username}")


def do_delete(username: str) -> None:
    with _authed_client() as client:
        user_id = _resolve_user_id(client, username)
        _check(client.delete(f"/api/admin/users/{user_id}?confirm=DELETE"))
    typer.echo(f"Deleted {username} and their workspace")


def do_reset_password(username: str, password: str) -> None:
    with _authed_client() as client:
        user_id = _resolve_user_id(client, username)
        _check(client.post(f"/api/admin/users/{user_id}/reset-password", json={"password": password}))
    typer.echo(f"Password reset for {username}")


# ---- typer bindings ----

@admin_app.command("login")
def login_cmd(url: str = typer.Option(None, "--url", help="Server URL (default RESUME_AGENT_URL)")) -> None:
    target = (url or api_url()).rstrip("/")
    username = typer.prompt("Username")
    password = typer.prompt("Password", hide_input=True)
    do_login(target, username, password)


@admin_app.command("logout")
def logout_cmd() -> None:
    do_logout()


@admin_app.command("whoami")
def whoami_cmd() -> None:
    do_whoami()


@admin_app.command("list-users")
def list_users_cmd() -> None:
    do_list_users()


@admin_app.command("invite")
def invite_cmd(expires_days: int = typer.Option(14, "--expires-days")) -> None:
    do_invite(expires_days)


@admin_app.command("set-role")
def set_role_cmd(username: str, role: str) -> None:
    do_set_role(username, role)


@admin_app.command("set-limits")
def set_limits_cmd(
    username: str,
    budget: int = typer.Option(None, "--budget"),
    max_jobs: int = typer.Option(None, "--max-jobs"),
    max_runs: int = typer.Option(None, "--max-runs"),
) -> None:
    do_set_limits(username, budget=budget, max_jobs=max_jobs, max_runs=max_runs)


@admin_app.command("usage")
def usage_cmd(days: int = typer.Option(7, "--days")) -> None:
    do_usage(days)


@admin_app.command("disable")
def disable_cmd(username: str) -> None:
    do_set_disabled(username, True)


@admin_app.command("enable")
def enable_cmd(username: str) -> None:
    do_set_disabled(username, False)


@admin_app.command("delete")
def delete_cmd(
    username: str,
    confirm: bool = typer.Option(False, "--confirm", help="Required: deletion removes the workspace"),
) -> None:
    if not confirm:
        raise typer.Exit(code=_fail("pass --confirm to delete a user and their workspace"))
    do_delete(username)


@admin_app.command("reset-password")
def reset_password_cmd(username: str) -> None:
    password = typer.prompt("New password", hide_input=True)
    do_reset_password(username, password)
```

Register in `cli.py` next to `profile_app`:

```python
from resume_agent.admin_cli import admin_app

app.add_typer(admin_app, name="admin")
```

Test-shim note: the tests monkeypatch `_make_client`; `do_login`'s session cookie must survive between the login POST and the PAT mint — that's why both calls share one `client`. The ASGI transport preserves cookies within a single `httpx.Client`, so the flow works unmodified.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_admin_cli.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/admin_cli.py src/resume_agent/cli.py tests/test_admin_cli.py
git commit -m "Adds HTTP-client admin CLI over the admin API"
```

---

### Task 6: SPA — register page + account page

**Files:**
- Create: `web/src/features/auth/RegisterPage.tsx`
- Create: `web/src/features/account/AccountPage.tsx`
- Modify: the router + login page (locate with `grep -rn "login" web/src/app web/src/features/auth --include=*.tsx -il`) to add the `/register` and `/account` routes and a "Have an invite code? Register" link on the login form
- Test: `web/src/features/account/AccountPage.test.tsx`

**Before writing components:** read `web/src/features/auth/` (the existing login page), `web/src/lib/api/` (fetch conventions, generated types from `contracts/ts/api.ts`), and the app-shell/router under `web/src/app/`. Mirror those exactly — the code below is the reference logic; restyle with the project's existing form/button/css primitives rather than the bare classNames shown.

- [ ] **Step 1: Register page**

```tsx
// web/src/features/auth/RegisterPage.tsx
import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";

export function RegisterPage() {
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const response = await fetch("/api/auth/register", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password, inviteCode }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        setError(body?.error?.message ?? `Registration failed (${response.status})`);
        return;
      }
      navigate("/login", { state: { registered: username } });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="auth-form">
      <h1>Create account</h1>
      <label>
        Username
        <input value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus />
      </label>
      <label>
        Password
        <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={8} />
      </label>
      <label>
        Invitation code
        <input value={inviteCode} onChange={(e) => setInviteCode(e.target.value)} required placeholder="inv_…" />
      </label>
      {error && <p role="alert">{error}</p>}
      <button type="submit" disabled={busy}>Register</button>
      <p>
        Already have an account? <Link to="/login">Sign in</Link>
      </p>
    </form>
  );
}
```

- [ ] **Step 2: Account page**

```tsx
// web/src/features/account/AccountPage.tsx
import { useEffect, useState } from "react";

type TokenInfo = { id: string; name: string; createdAt: string; lastUsedAt: string | null };
type Usage = { weightedTotal: number; ownKeyWeightedTotal: number; budget: number };

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.error?.message ?? `${response.status}`);
  }
  return response.json() as Promise<T>;
}

export function AccountPage() {
  const [tokens, setTokens] = useState<TokenInfo[]>([]);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [freshToken, setFreshToken] = useState<string | null>(null);
  const [tokenName, setTokenName] = useState("");
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [message, setMessage] = useState<string | null>(null);

  async function refresh() {
    const [tokenList, usageBody] = await Promise.all([
      api<{ tokens: TokenInfo[] }>("/api/account/tokens"),
      api<Usage>("/api/account/usage"),
    ]);
    setTokens(tokenList.tokens);
    setUsage(usageBody);
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function mintToken(event: React.FormEvent) {
    event.preventDefault();
    const minted = await api<{ token: string }>("/api/account/tokens", {
      method: "POST",
      body: JSON.stringify({ name: tokenName }),
    });
    setFreshToken(minted.token);
    setTokenName("");
    await refresh();
  }

  async function revoke(id: string) {
    await api(`/api/account/tokens/${id}`, { method: "DELETE" });
    await refresh();
  }

  async function changePassword(event: React.FormEvent) {
    event.preventDefault();
    try {
      await api("/api/account/password", {
        method: "POST",
        body: JSON.stringify({ currentPassword: current, newPassword: next }),
      });
      setMessage("Password changed.");
      setCurrent("");
      setNext("");
    } catch (error) {
      setMessage(String(error));
    }
  }

  const percent = usage && usage.budget > 0
    ? Math.min(100, Math.round((usage.weightedTotal / usage.budget) * 100))
    : 0;

  return (
    <div className="account-page">
      <h1>Account</h1>

      <section>
        <h2>Usage this week</h2>
        {usage && (
          <p>
            {usage.weightedTotal.toLocaleString()} of{" "}
            {usage.budget === 0 ? "unlimited" : usage.budget.toLocaleString()} weighted tokens
            {usage.budget > 0 && ` (${percent}%)`}
            {usage.ownKeyWeightedTotal > 0 &&
              ` — plus ${usage.ownKeyWeightedTotal.toLocaleString()} on your own key`}
          </p>
        )}
      </section>

      <section>
        <h2>Personal access tokens</h2>
        {freshToken && (
          <p role="alert">
            Copy this token now — it will not be shown again: <code>{freshToken}</code>
          </p>
        )}
        <form onSubmit={mintToken}>
          <input
            value={tokenName}
            onChange={(e) => setTokenName(e.target.value)}
            placeholder="Token name (e.g. cli)"
            required
          />
          <button type="submit">Create token</button>
        </form>
        <ul>
          {tokens.map((token) => (
            <li key={token.id}>
              {token.name} — created {new Date(token.createdAt).toLocaleDateString()}
              {token.lastUsedAt && `, last used ${new Date(token.lastUsedAt).toLocaleDateString()}`}
              <button onClick={() => void revoke(token.id)}>Revoke</button>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2>Change password</h2>
        <form onSubmit={changePassword}>
          <input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} placeholder="Current password" required />
          <input type="password" value={next} onChange={(e) => setNext(e.target.value)} placeholder="New password" required minLength={8} />
          <button type="submit">Change password</button>
        </form>
        {message && <p role="status">{message}</p>}
      </section>

      <section>
        <h2>Export my workspace</h2>
        <p>
          Downloads everything in your workspace — including your stored
          secrets. Treat the archive as secret material.
        </p>
        <a href="/api/account/export" download>
          Download workspace archive
        </a>
      </section>
    </div>
  );
}
```

(Note: the export link rides the session cookie — same-origin `<a>` downloads send cookies, so no link token is needed here; keep it a plain anchor.)

- [ ] **Step 3: Route registration**

Add `/register` (public, alongside `/login`) and `/account` (authenticated) to the router found by the grep; add the register link to the login page. Follow the existing route-guard pattern for authenticated pages.

- [ ] **Step 4: Component test**

```tsx
// web/src/features/account/AccountPage.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import { vi, describe, it, expect, beforeEach } from "vitest";

import { AccountPage } from "./AccountPage";

describe("AccountPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo) => {
      const url = String(input);
      const body = url.endsWith("/api/account/tokens")
        ? { tokens: [{ id: "t1", name: "cli", createdAt: "2026-07-12T00:00:00Z", lastUsedAt: null }] }
        : { weightedTotal: 1000, ownKeyWeightedTotal: 0, budget: 10000000 };
      return new Response(JSON.stringify(body), { status: 200 });
    }));
  });

  it("renders usage meter and token list", async () => {
    render(<AccountPage />);
    await waitFor(() => {
      expect(screen.getByText(/weighted tokens/)).toBeInTheDocument();
      expect(screen.getByText(/cli/)).toBeInTheDocument();
    });
  });
});
```

- [ ] **Step 5: Run web tests**

Run: `cd web && npx vitest run`
Expected: green (including existing suites)

- [ ] **Step 6: Commit**

```bash
git add web/src/features/auth/RegisterPage.tsx web/src/features/account web/src/app
git commit -m "Adds register and account pages to the SPA"
```

---

### Task 7: SPA admin page + contract regen + docs

**Files:**
- Create: `web/src/features/admin/AdminPage.tsx`
- Modify: router + nav (admin page visible only when `/api/auth/me` returns `role === "admin"`)
- Modify: `contracts/openapi.json` + `contracts/ts/api.ts` (regenerated)
- Modify: `CLAUDE.md`, `README.md` (admin surfaces section)
- Test: `web/src/features/admin/AdminPage.test.tsx`, drift gate

**Interfaces:**
- Consumes: every endpoint from Tasks 1-3.
- Produces: one admin page with three panels — user table (role/usage/limits editors, disable/enable, delete with confirm prompt), invite panel (mint + copy-to-clipboard + list/revoke), system defaults panel. Nav link rendered only for admins (extend the existing `/api/auth/me` consumer — Plan 2 added `role` to `MeResponse`).

- [ ] **Step 1: Admin page component**

```tsx
// web/src/features/admin/AdminPage.tsx
import { useEffect, useState } from "react";

type AdminUser = {
  id: string; username: string; role: string; createdAt: string;
  disabledAt: string | null; weeklyTokenBudget: number | null;
  maxActiveJobs: number | null; maxConcurrentRuns: number | null;
  weeklyUsage: number; activeJobs: number;
};
type Invite = {
  id: string; createdBy: string; createdAt: string; expiresAt: string;
  usedBy: string | null; usedAt: string | null; revokedAt: string | null;
};
type Defaults = { weeklyTokenBudget: number; maxActiveJobs: number; maxConcurrentRuns: number };

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.error?.message ?? `${response.status}`);
  }
  return response.status === 204 ? (undefined as T) : (response.json() as Promise<T>);
}

export function AdminPage() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [defaults, setDefaults] = useState<Defaults | null>(null);
  const [freshInvite, setFreshInvite] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function refresh() {
    try {
      const [userList, inviteList, defaultsBody] = await Promise.all([
        api<{ users: AdminUser[] }>("/api/admin/users"),
        api<{ invites: Invite[] }>("/api/admin/invites"),
        api<Defaults>("/api/admin/system/defaults"),
      ]);
      setUsers(userList.users);
      setInvites(inviteList.invites);
      setDefaults(defaultsBody);
    } catch (e) {
      setError(String(e));
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  async function patchUser(id: string, patch: Record<string, unknown>) {
    await api(`/api/admin/users/${id}`, { method: "PATCH", body: JSON.stringify(patch) });
    await refresh();
  }

  async function deleteUser(user: AdminUser) {
    if (!window.confirm(`Delete ${user.username} AND their entire workspace? This cannot be undone.`)) return;
    await api(`/api/admin/users/${user.id}?confirm=DELETE`, { method: "DELETE" });
    await refresh();
  }

  async function mintInvite() {
    const minted = await api<{ code: string }>("/api/admin/invites", {
      method: "POST",
      body: JSON.stringify({}),
    });
    setFreshInvite(minted.code);
    await refresh();
  }

  async function saveDefaults(event: React.FormEvent) {
    event.preventDefault();
    if (!defaults) return;
    await api("/api/admin/system/defaults", { method: "PUT", body: JSON.stringify(defaults) });
    await refresh();
  }

  return (
    <div className="admin-page">
      <h1>Administration</h1>
      {error && <p role="alert">{error}</p>}

      <section>
        <h2>Users</h2>
        <table>
          <thead>
            <tr>
              <th>User</th><th>Role</th><th>7-day usage</th><th>Jobs</th>
              <th>Budget</th><th>Max jobs</th><th>Max runs</th><th></th>
            </tr>
          </thead>
          <tbody>
            {users.map((user) => (
              <tr key={user.id} className={user.disabledAt ? "disabled" : ""}>
                <td>{user.username}{user.disabledAt && " (disabled)"}</td>
                <td>
                  <select
                    value={user.role}
                    onChange={(e) => void patchUser(user.id, { role: e.target.value })}
                  >
                    <option value="user">user</option>
                    <option value="admin">admin</option>
                  </select>
                </td>
                <td>{user.weeklyUsage.toLocaleString()}</td>
                <td>{user.activeJobs}</td>
                <LimitCell user={user} field="weeklyTokenBudget" onSave={patchUser} />
                <LimitCell user={user} field="maxActiveJobs" onSave={patchUser} />
                <LimitCell user={user} field="maxConcurrentRuns" onSave={patchUser} />
                <td>
                  <button onClick={() => void patchUser(user.id, { disabled: !user.disabledAt })}>
                    {user.disabledAt ? "Enable" : "Disable"}
                  </button>
                  <button onClick={() => void deleteUser(user)}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <h2>Invitations</h2>
        {freshInvite && (
          <p role="alert">
            Copy now — shown once: <code>{freshInvite}</code>{" "}
            <button onClick={() => void navigator.clipboard.writeText(freshInvite)}>Copy</button>
          </p>
        )}
        <button onClick={() => void mintInvite()}>New invite (14 days)</button>
        <ul>
          {invites.map((invite) => (
            <li key={invite.id}>
              {invite.id} — expires {new Date(invite.expiresAt).toLocaleDateString()}
              {invite.usedAt && ` — used`}
              {invite.revokedAt && ` — revoked`}
              {!invite.usedAt && !invite.revokedAt && (
                <button
                  onClick={() =>
                    void api(`/api/admin/invites/${invite.id}`, { method: "DELETE" }).then(refresh)
                  }
                >
                  Revoke
                </button>
              )}
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2>System defaults</h2>
        {defaults && (
          <form onSubmit={saveDefaults}>
            <label>
              Weekly token budget
              <input
                type="number"
                value={defaults.weeklyTokenBudget}
                onChange={(e) => setDefaults({ ...defaults, weeklyTokenBudget: Number(e.target.value) })}
              />
            </label>
            <label>
              Max active jobs
              <input
                type="number"
                value={defaults.maxActiveJobs}
                onChange={(e) => setDefaults({ ...defaults, maxActiveJobs: Number(e.target.value) })}
              />
            </label>
            <label>
              Max concurrent runs
              <input
                type="number"
                value={defaults.maxConcurrentRuns}
                onChange={(e) => setDefaults({ ...defaults, maxConcurrentRuns: Number(e.target.value) })}
              />
            </label>
            <button type="submit">Save defaults</button>
            <p>0 = unlimited. Per-user overrides win over these defaults.</p>
          </form>
        )}
      </section>
    </div>
  );
}

function LimitCell({
  user,
  field,
  onSave,
}: {
  user: AdminUser;
  field: "weeklyTokenBudget" | "maxActiveJobs" | "maxConcurrentRuns";
  onSave: (id: string, patch: Record<string, unknown>) => Promise<void>;
}) {
  const value = user[field];
  return (
    <td>
      <input
        type="number"
        placeholder="default"
        defaultValue={value ?? ""}
        onBlur={(e) => {
          const raw = e.target.value.trim();
          const next = raw === "" ? null : Number(raw);
          if (next !== value) void onSave(user.id, { [field]: next });
        }}
      />
    </td>
  );
}
```

- [ ] **Step 2: Nav gating**

Extend the `/api/auth/me` consumer (the auth context/hook found by `grep -rn "auth/me" web/src`): store `role`, render the Admin nav link (and route) only when `role === "admin"`. Non-admins deep-linking to `/admin` get the API's 403s — render the error state.

- [ ] **Step 3: Component test**

```tsx
// web/src/features/admin/AdminPage.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import { vi, describe, it, expect, beforeEach } from "vitest";

import { AdminPage } from "./AdminPage";

describe("AdminPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo) => {
      const url = String(input);
      let body: unknown = {};
      if (url.includes("/api/admin/users")) {
        body = { users: [{
          id: "u1", username: "owner", role: "admin", createdAt: "2026-07-12T00:00:00Z",
          disabledAt: null, weeklyTokenBudget: null, maxActiveJobs: null,
          maxConcurrentRuns: null, weeklyUsage: 12345, activeJobs: 7,
        }] };
      } else if (url.includes("/api/admin/invites")) {
        body = { invites: [] };
      } else if (url.includes("/api/admin/system/defaults")) {
        body = { weeklyTokenBudget: 10000000, maxActiveJobs: 2000, maxConcurrentRuns: 2 };
      }
      return new Response(JSON.stringify(body), { status: 200 });
    }));
  });

  it("renders the user table and defaults", async () => {
    render(<AdminPage />);
    await waitFor(() => {
      expect(screen.getByText("owner")).toBeInTheDocument();
      expect(screen.getByText(/12,345/)).toBeInTheDocument();
      expect(screen.getByDisplayValue("10000000")).toBeInTheDocument();
    });
  });
});
```

- [ ] **Step 4: Contract regen + drift gate + docs**

Run: `bash scripts/gen_ts_client.sh`
Run: `.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -v` → green
Run: `cd web && npx vitest run` → green
Run: `.venv/Scripts/python.exe -m pytest -q && ruff check` → full suite green

Append to CLAUDE.md's tenancy section:

```markdown
Admin surfaces: `/api/admin/users|invites|system/*` behind `require_admin`
(403 FORBIDDEN otherwise) — one surface, two clients (SPA Admin page +
`resume-agent admin <cmd>` HTTP CLI, PAT cached at
`~/.resume-agent/credentials.json`, server from RESUME_AGENT_URL). Account
self-service: password change (reissues the session cookie), PAT CRUD,
usage meter, and workspace export (`/api/account/export` — archive contains
secrets.env). Delete-user: confirm flag, refuses last admin/self/in-flight
runs, evicts the engine before removing the workspace directory.
```

Add a short "Multi-user" section to README.md: how to seed the first admin (env vars), invite a member (admin page or CLI), and what members can/can't do (web-UI-only, own workspace, budgets).

- [ ] **Step 5: Commit**

```bash
git add web/src/features/admin web/src/app contracts CLAUDE.md README.md
git commit -m "Adds SPA admin page with contract regeneration"
```

---

### Task 8: Whole-root import/export under multi-user

**Files:**
- Modify: `src/resume_agent/api/routers/admin.py` (import handler engine lifecycle; both routes behind `require_admin`)
- Test: `tests/api/test_admin_root_import_export.py`

**Interfaces:**
- Consumes: Plan 1 `EngineRegistry.close_all`, `ensure_bootstrapped`, `build_context`, `init_system_db`, `make_system_engine`; Task 1's `require_admin`.
- Produces: the existing `GET /api/admin/export` / `POST /api/admin/import` operate on the **whole** data root (`system.db` + `users/`) in multi-user mode. Export already archives `app.state.data_dir` — it only needs the WAL snapshot special-casing to also cover `system.db` and each workspace DB (check `services/backup.export_data_root`'s `_sqlite_file` handling: it snapshots the DB named by `db_url`; extend it to snapshot **every** `*.db` under the root the same way, which also fixes workspace DBs). Import gains the multi-user engine lifecycle: dispose registry + system engine before the swap, then rebuild system engine → `init_system_db` → `ensure_bootstrapped` → fresh registry + default context after. Both routes require the admin role in multi-user mode.

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_admin_root_import_export.py
import io
import tarfile

from tests.api.conftest import login
from tests.api.test_tenancy_isolation import _register


def test_export_contains_system_db_and_workspaces(mu_app, mu_client):
    _register(mu_app, mu_client, "alice")
    login(mu_client)
    response = mu_client.get("/api/admin/export")
    assert response.status_code == 200
    names = tarfile.open(fileobj=io.BytesIO(response.content), mode="r:gz").getnames()
    assert any("system.db" in name for name in names)
    assert any("users" in name for name in names)


def test_non_admin_cannot_export(mu_app, mu_client):
    _register(mu_app, mu_client, "alice")
    login(mu_client, "alice", "pw")
    assert mu_client.get("/api/admin/export").status_code == 403


def test_import_roundtrip_rebuilds_tenancy(mu_app, mu_client):
    _register(mu_app, mu_client, "alice")
    login(mu_client)
    exported = mu_client.get("/api/admin/export").content
    response = mu_client.post(
        "/api/admin/import?confirm=REPLACE",
        files={"file": ("root.tar.gz", exported, "application/gzip")},
    )
    assert response.status_code == 200, response.text
    # tenancy still works after the swap: both users can log in
    mu_client.cookies.clear()
    login(mu_client, "alice", "pw")
    assert mu_client.get("/api/jobs").status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_admin_root_import_export.py -v`
Expected: FAIL — non-admin export is 200 (no role gate), and import errors or leaves stale engines (login after import fails).

- [ ] **Step 3: Implement**

In `api/routers/admin.py`:

1. Add `ctx: UserContext = Depends(require_admin)` to both route signatures when `request.app.state.system_engine is not None` — simplest uniform shape: add a small local dependency that no-ops in legacy mode:

```python
from resume_agent.api.deps import require_admin


def require_admin_when_multiuser(request: Request) -> None:
    if getattr(request.app.state, "system_engine", None) is not None:
        require_admin()
```

and add `dependencies=[Depends(require_admin_when_multiuser)]` to the router constructor.

2. Replace the import handler's engine rebuild block (`finally:` clause) with a multi-user-aware rebuild:

```python
        finally:
            registry = request.app.state.engine_registry
            if registry is not None:
                registry.close_all()
            system_engine = request.app.state.system_engine
            if system_engine is not None:
                system_engine.dispose()
            request.app.state.engine.dispose()
            if system_engine is not None:
                from resume_agent.tenancy.bootstrap import build_context, ensure_bootstrapped
                from resume_agent.tenancy.engines import EngineRegistry
                from resume_agent.tenancy.system_db import init_system_db, make_system_engine
                from resume_agent.tenancy import usage

                new_system = make_system_engine(request.app.state.data_dir)
                init_system_db(new_system)
                admin = ensure_bootstrapped(
                    request.app.state.data_dir, new_system, request.app.state.settings
                )
                new_registry = EngineRegistry()
                ctx = build_context(
                    admin, request.app.state.data_dir, request.app.state.settings, new_registry
                )
                request.app.state.system_engine = new_system
                request.app.state.engine_registry = new_registry
                request.app.state.default_context = ctx
                request.app.state.engine = ctx.engine
                usage.configure(new_system)
            else:
                engine = make_engine(request.app.state.db_url)
                init_db(engine)
                request.app.state.engine = engine
```

Also pass `before_swap=` a callable that disposes the registry AND the system engine (the archived root's DB files are open until then). Check whether `export_data_root` snapshots only the `db_url`-named file; if so, extend it to snapshot every `*.db` under the root (system.db + each workspace DB) via the existing `sqlite_snapshot` helper, keeping non-DB files copied as before.

- [ ] **Step 4: Run tests + full suite**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_admin_root_import_export.py -v` → 3 passed
Run: `.venv/Scripts/python.exe -m pytest -q && ruff check` → green (legacy import/export tests unaffected via the no-op dependency).

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/api/routers/admin.py src/resume_agent/services/backup.py tests/api/test_admin_root_import_export.py
git commit -m "Rebuilds tenancy engines across whole-root import under multi-user"
```
