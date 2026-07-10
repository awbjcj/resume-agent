# Railway Deployment + Single-User Login Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy resume-agent to Railway as a single-tenant instance behind a session-cookie login, with the whole Data root on one volume and browser connectors honestly degraded (spec: `docs/superpowers/specs/2026-07-10-railway-deploy-design.md`, ADR 0002).

**Architecture:** One Railway service: multi-stage Docker (node builds `web/dist` → python:3.13-slim runs FastAPI, which already serves the SPA). Auth adds a stateless HMAC session cookie beside the existing bearer token, joined inside the single guard `require_token`. Persistence is one volume at `/app/data`; an entrypoint symlinks `output/`, `config/`, `.env` into it. Admin export/import moves the Data root as one tarball (full replace, VACUUM-INTO DB snapshot).

**Tech Stack:** FastAPI, pydantic-settings, SQLModel/SQLite (WAL), stdlib `hashlib`/`hmac` (no new deps), React 19 + React Query + openapi-fetch, MSW/vitest, Docker, Railway.

## Global Constraints

- Python `>=3.13` (pyproject); run tests with `.venv/Scripts/python.exe -m pytest` (offline — no API key, no network, browser faked).
- Lint gate: `ruff check` must pass before every commit.
- Wire format is camelCase: every new request/response model extends `CamelModel` (`src/resume_agent/api/schemas/base.py`).
- Errors use the envelope via `ApiException(status, code, message)` (`src/resume_agent/api/errors.py`).
- Any change to routers/schemas changes the OpenAPI contract: run `bash scripts/gen_ts_client.sh`, commit `contracts/openapi.json`, `contracts/ts/api.ts`, and `web/src/lib/api/schema.ts` together — `tests/api/test_openapi_contract.py` is the drift gate.
- No new Python dependencies anywhere in this plan (auth is stdlib; export/import is `tarfile`/`sqlite3`).
- Frontend tests: `cd web && npm run test:run`. Frontend lint: `cd web && npm run lint`.
- No business logic in routers — routers adapt; policy lives in `services/` or the module the task creates.
- Session-auth tests MUST build their client as `TestClient(app, base_url="https://testserver")` — the session cookie is `Secure`, and httpx will not send Secure cookies back over plain `http://testserver`.

## Correctness Amendments (authoritative)

These amendments override conflicting snippets below. They reconcile the plan
with the approved design, current repository contracts, and the failure modes
of a mounted Railway volume.

1. **Make credential checks timing-uniform.** Login always computes
   `verify_password()` and compares usernames with `hmac.compare_digest()`;
   never short-circuit password hashing when the username is wrong. The fixed
   failure delay is additive and tests prove both bad-user and bad-password
   paths exercise verification.
2. **`/api/auth/me` is the public state probe.** It always returns 200 with
   `{username, authRequired}` so the SPA can distinguish open mode from a
   missing/expired session without a redirect loop. The design's older 401
   wording is superseded.
3. **Preserve every platform-owned runtime setting on web config refresh.** In
   addition to DB/token/auth fields, preserve `browser_enabled`; otherwise a
   Secrets-page save would reset Railway's `BROWSER_ENABLED=false` to the local
   default and launch browsers in cloud.
4. **Fail closed in the auth gate.** While `/auth/me` is pending render a
   skeleton; on a non-401/network error render an accessible retry state. Never
   render protected application children when auth state is unknown. Login
   forms use `FieldGroup`/`Field`, pending buttons compose `Spinner`, and button
   icons use `data-icon` without manual sizing.
5. **Report disabled browser sources instead of dropping them.** Scrape targets
   and LinkedIn remain in pull results as connector-level failures with
   `requires a local browser (browser_enabled=false)`. The dedicated LinkedIn
   scrape endpoint/service returns the same explicit failure and never launches
   Playwright. Tesla remains isolated per URL; Adzuna remains snippet-only.
6. **Verify existing symlinks.** `prepare_data_root` accepts an existing symlink
   only when it resolves to the intended data-root target; a stale or hostile
   link is an error. Tests cover wrong-target links and idempotence.
7. **Import is staged and rollback-safe.** Validate every tar member and extract
   to staging before touching live state; reject empty/no-file archives as
   `INVALID_ARCHIVE`; then perform a same-volume child swap with a rollback
   directory because `/app/data` itself is a mount point and cannot be renamed.
   If any move fails, restore the original root. After disposing the engine, the
   router recreates/rebinds it in `finally` on success or failure, then refreshes
   settings only after a successful import.
8. **Pack only restorable archives.** The local packer rejects symlinks/special
   files, omits SQLite sidecars, snapshots each `.db`, and never emits an empty
   seed silently. Tests round-trip its output through `import_data_root`.
9. **Deployment docs match Windows and Railway reality.** Keep the documented
   one-volume/no-replicas constraint, ignore all `*.tar.gz` secret backups in
   Docker context, and give PowerShell-safe build/run/seed examples alongside
   POSIX examples. The round-trip restore instructions must place archive-root
   `config/`, `output/`, and `.env` beside local `data/`, not under it.
10. **Materialize ignored runtime configs.** A clean Git checkout contains
    tracked `*.example` files but not user-owned `review.yaml`, `search.yaml`,
    `render.yaml`, and related runtime files. `prepare_data_root` copies missing
    defaults on every boot and materializes each missing runtime path from its
    example without overwriting volume edits.

---

### Task 1: Auth primitives + Settings fields + `hash-password` CLI

**Files:**
- Create: `src/resume_agent/api/auth.py`
- Modify: `src/resume_agent/config.py` (add 4 fields after `api_token`, ~line 34)
- Modify: `src/resume_agent/cli.py` (add `hash-password` command near `serve_cmd`, ~line 818)
- Test: `tests/api/test_auth_primitives.py`

**Interfaces:**
- Consumes: `Settings` (`resume_agent.config`).
- Produces (used by Tasks 2, 4):
  - `Settings.auth_username: str = ""`, `Settings.auth_password_hash: str = ""`, `Settings.session_secret: str = ""`, `Settings.browser_enabled: bool = True`
  - `auth.SESSION_COOKIE: str = "ra_session"`, `auth.SESSION_LIFETIME_SECONDS: int`
  - `auth.hash_password(password: str, *, iterations: int = 120_000) -> str`
  - `auth.verify_password(password: str, stored: str) -> bool`
  - `auth.session_auth_configured(settings: Settings) -> bool`
  - `auth.issue_session(settings: Settings, *, now: float | None = None) -> str`
  - `auth.verify_session(token: str, settings: Settings, *, now: float | None = None) -> str | None`

- [ ] **Step 1: Write the failing tests**

Create `tests/api/test_auth_primitives.py`:

```python
"""Password hashing + stateless session tokens (spec 2026-07-10 §2)."""

from resume_agent.api.auth import (
    SESSION_LIFETIME_SECONDS,
    hash_password,
    issue_session,
    session_auth_configured,
    verify_password,
    verify_session,
)
from resume_agent.config import Settings


def _settings(**kw) -> Settings:
    defaults = dict(
        auth_username="owner",
        auth_password_hash=hash_password("hunter2"),
        session_secret="s3cret",
    )
    defaults.update(kw)
    return Settings(_env_file=None, **defaults)


def test_hash_password_roundtrip():
    stored = hash_password("hunter2")
    assert stored.startswith("pbkdf2:")
    assert verify_password("hunter2", stored)
    assert not verify_password("wrong", stored)


def test_hash_password_salts_differ():
    assert hash_password("x") != hash_password("x")


def test_verify_password_rejects_malformed():
    assert not verify_password("x", "")
    assert not verify_password("x", "not-a-hash")
    assert not verify_password("x", "pbkdf2:banana:00:00")


def test_session_auth_configured_requires_all_three():
    assert session_auth_configured(_settings())
    assert not session_auth_configured(_settings(auth_username=""))
    assert not session_auth_configured(_settings(auth_password_hash=""))
    assert not session_auth_configured(_settings(session_secret=""))


def test_session_roundtrip():
    s = _settings()
    token = issue_session(s, now=1000.0)
    assert verify_session(token, s, now=1000.0) == "owner"


def test_session_expiry():
    s = _settings()
    token = issue_session(s, now=1000.0)
    assert verify_session(token, s, now=1000.0 + SESSION_LIFETIME_SECONDS + 1) is None


def test_session_rejects_tampering_and_wrong_secret():
    s = _settings()
    token = issue_session(s, now=1000.0)
    assert verify_session(token + "0", s, now=1000.0) is None
    assert verify_session(token.replace("owner", "admin", 1), s, now=1000.0) is None
    assert verify_session(token, _settings(session_secret="other"), now=1000.0) is None
    assert verify_session("garbage", s) is None
    assert verify_session("", s) is None


def test_session_none_when_unconfigured():
    s = _settings()
    token = issue_session(s, now=1000.0)
    assert verify_session(token, _settings(session_secret=""), now=1000.0) is None


def test_settings_browser_enabled_default_true():
    assert Settings(_env_file=None).browser_enabled is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_auth_primitives.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.api.auth'`

- [ ] **Step 3: Add the Settings fields**

In `src/resume_agent/config.py`, directly after the `api_token` field (~line 34), add:

```python
    # Single-account session auth (spec 2026-07-10). All three must be set for
    # the session guard to activate; unset = local-dev open mode.
    auth_username: str = ""
    auth_password_hash: str = ""  # produced by `resume-agent hash-password`
    session_secret: str = ""  # HMAC key for the session cookie; rotating it logs out
    # False on Railway: skips connectors that need a visible local browser.
    browser_enabled: bool = True
```

- [ ] **Step 4: Write `src/resume_agent/api/auth.py`**

```python
"""Single-account session auth: PBKDF2 password hashes + stateless HMAC cookies.

No server-side session store: the cookie is `username:expiry:hmac`. Rotating
``session_secret`` invalidates every session; changing the password alone does
not (accepted for one user — see the 2026-07-10 deploy spec §2).
Stdlib only — no new dependency.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from resume_agent.config import Settings

SESSION_COOKIE = "ra_session"
SESSION_LIFETIME_SECONDS = 30 * 24 * 3600
_PBKDF2_ITERATIONS = 120_000


def hash_password(password: str, *, iterations: int = _PBKDF2_ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"pbkdf2:{iterations}:{salt.hex()}:{digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations_s, salt_hex, hash_hex = stored.split(":")
        if scheme != "pbkdf2":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations_s)
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), hash_hex)


def session_auth_configured(settings: Settings) -> bool:
    return bool(
        settings.auth_username
        and settings.auth_password_hash
        and settings.session_secret
    )


def _sign(settings: Settings, payload: str) -> str:
    return hmac.new(
        settings.session_secret.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()


def issue_session(settings: Settings, *, now: float | None = None) -> str:
    expiry = int((now if now is not None else time.time()) + SESSION_LIFETIME_SECONDS)
    payload = f"{settings.auth_username}:{expiry}"
    return f"{payload}:{_sign(settings, payload)}"


def verify_session(
    token: str, settings: Settings, *, now: float | None = None
) -> str | None:
    """Return the username for a valid, unexpired token; None otherwise."""
    if not session_auth_configured(settings):
        return None
    try:
        username, expiry_s, sig = token.rsplit(":", 2)
        expiry = int(expiry_s)
    except (ValueError, TypeError):
        return None
    if not hmac.compare_digest(sig, _sign(settings, f"{username}:{expiry}")):
        return None
    if (now if now is not None else time.time()) >= expiry:
        return None
    if username != settings.auth_username:
        return None
    return username
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_auth_primitives.py -v`
Expected: all PASS

- [ ] **Step 6: Add the `hash-password` CLI command**

In `src/resume_agent/cli.py`, directly above `serve_cmd` (~line 818), add:

```python
@app.command("hash-password")
def hash_password_cmd(
    password: str = typer.Option(
        ..., prompt=True, hide_input=True, confirmation_prompt=True,
        help="Password to hash for AUTH_PASSWORD_HASH.",
    ),
) -> None:
    """Print the PBKDF2 hash to set as AUTH_PASSWORD_HASH (Railway env var)."""
    from resume_agent.api.auth import hash_password

    typer.echo(hash_password(password))
```

Verify manually: `.venv/Scripts/python.exe -m resume_agent.cli hash-password --password test123`
Expected: one line starting `pbkdf2:120000:`

- [ ] **Step 7: Full suite + lint, then commit**

Run: `.venv/Scripts/python.exe -m pytest && ruff check`
Expected: all pass.

```bash
git add src/resume_agent/api/auth.py src/resume_agent/config.py src/resume_agent/cli.py tests/api/test_auth_primitives.py
git commit -m "feat: session-auth primitives, settings fields, hash-password CLI"
```

---

### Task 2: Auth endpoints + combined guard

**Files:**
- Create: `src/resume_agent/api/schemas/auth.py`
- Create: `src/resume_agent/api/routers/auth.py`
- Modify: `src/resume_agent/api/deps.py` (`require_token` ~line 26, `refresh_app_settings` ~line 54)
- Modify: `src/resume_agent/api/app.py` (router import block ~line 16, registration ~line 119)
- Modify (generated): `contracts/openapi.json`, `contracts/ts/api.ts`, `web/src/lib/api/schema.ts`
- Test: `tests/api/test_auth_router.py`

**Interfaces:**
- Consumes (Task 1): `auth.SESSION_COOKIE`, `auth.SESSION_LIFETIME_SECONDS`, `auth.session_auth_configured`, `auth.issue_session`, `auth.verify_session`, `auth.verify_password`; `Settings.auth_*`, `Settings.session_secret`.
- Produces (used by Task 3 via the regenerated TS schema):
  - `POST /api/auth/login` body `{username, password}` → 200 `{username, authRequired}` + `ra_session` cookie; 401 envelope on bad credentials; 400 `AUTH_NOT_CONFIGURED` when unconfigured.
  - `POST /api/auth/logout` → 200 `{"status": "ok"}`, clears cookie.
  - `GET /api/auth/me` → always 200 `{username: string|null, authRequired: bool}` (never 401 — the SPA gate polls it).
  - `require_token` (same name/registration) now passes on a valid session cookie OR the bearer/query token.

- [ ] **Step 1: Write the failing tests**

Create `tests/api/test_auth_router.py`:

```python
"""Login/logout/me + the combined cookie-or-bearer guard (spec 2026-07-10 §2)."""

import pytest
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.api.auth import hash_password
from resume_agent.api.deps import refresh_app_settings
from resume_agent.config import Settings


def _auth_env(tmp_path, extra: str = ""):
    env = tmp_path / ".env"
    env.write_text(
        "AUTH_USERNAME=owner\n"
        f"AUTH_PASSWORD_HASH={hash_password('hunter2')}\n"
        "SESSION_SECRET=test-secret\n" + extra,
        encoding="utf-8",
    )
    return env


def _client(app) -> TestClient:
    # base_url MUST be https: the cookie is Secure and httpx drops Secure
    # cookies over plain http.
    return TestClient(app, base_url="https://testserver")


@pytest.fixture(autouse=True)
def _no_login_delay(monkeypatch):
    from resume_agent.api.routers import auth as auth_router

    monkeypatch.setattr(auth_router, "FAILED_LOGIN_DELAY_SECONDS", 0.0)


def test_login_sets_cookie_and_unlocks_api(tmp_path):
    app = create_app(db_url="sqlite://", env_path=_auth_env(tmp_path))
    with _client(app) as client:
        assert client.get("/api/pipeline").status_code == 401  # locked
        resp = client.post(
            "/api/auth/login", json={"username": "owner", "password": "hunter2"}
        )
        assert resp.status_code == 200
        assert resp.json() == {"username": "owner", "authRequired": True}
        assert "ra_session" in resp.cookies
        assert client.get("/api/pipeline").status_code == 200  # cookie unlocks


def test_login_rejects_bad_credentials(tmp_path):
    app = create_app(db_url="sqlite://", env_path=_auth_env(tmp_path))
    with _client(app) as client:
        resp = client.post(
            "/api/auth/login", json={"username": "owner", "password": "nope"}
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "UNAUTHORIZED"


def test_login_400_when_unconfigured():
    app = create_app(db_url="sqlite://")
    with _client(app) as client:
        resp = client.post(
            "/api/auth/login", json={"username": "x", "password": "y"}
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "AUTH_NOT_CONFIGURED"


def test_me_reflects_state(tmp_path):
    app = create_app(db_url="sqlite://", env_path=_auth_env(tmp_path))
    with _client(app) as client:
        assert client.get("/api/auth/me").json() == {
            "username": None, "authRequired": True,
        }
        client.post("/api/auth/login", json={"username": "owner", "password": "hunter2"})
        assert client.get("/api/auth/me").json() == {
            "username": "owner", "authRequired": True,
        }


def test_me_open_mode():
    app = create_app(db_url="sqlite://")
    with _client(app) as client:
        assert client.get("/api/auth/me").json() == {
            "username": None, "authRequired": False,
        }


def test_logout_clears_session(tmp_path):
    app = create_app(db_url="sqlite://", env_path=_auth_env(tmp_path))
    with _client(app) as client:
        client.post("/api/auth/login", json={"username": "owner", "password": "hunter2"})
        assert client.get("/api/pipeline").status_code == 200
        client.post("/api/auth/logout")
        assert client.get("/api/pipeline").status_code == 401


def test_bearer_still_works_beside_sessions(tmp_path):
    app = create_app(
        db_url="sqlite://", env_path=_auth_env(tmp_path, "API_TOKEN=cli-token\n")
    )
    with _client(app) as client:
        assert client.get("/api/pipeline").status_code == 401
        assert (
            client.get(
                "/api/pipeline", headers={"Authorization": "Bearer cli-token"}
            ).status_code
            == 200
        )
        assert client.get("/api/pipeline?token=cli-token").status_code == 200


def test_open_mode_unchanged():
    app = create_app(db_url="sqlite://")
    with _client(app) as client:
        assert client.get("/api/pipeline").status_code == 200


def test_refresh_preserves_auth_fields(tmp_path):
    app = create_app(db_url="sqlite://", env_path=_auth_env(tmp_path))
    with _client(app):
        refresh_app_settings(app, Settings(_env_file=None))
        s = app.state.settings
        assert s.auth_username == "owner"
        assert s.session_secret == "test-secret"
        assert s.auth_password_hash.startswith("pbkdf2:")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_auth_router.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.api.routers.auth'`

- [ ] **Step 3: Write the schema module**

Create `src/resume_agent/api/schemas/auth.py`:

```python
"""Auth wire models (camelCase via CamelModel)."""

from __future__ import annotations

from resume_agent.api.schemas.base import CamelModel


class LoginRequest(CamelModel):
    username: str
    password: str


class MeResponse(CamelModel):
    username: str | None = None
    auth_required: bool = False
```

- [ ] **Step 4: Write the router**

Create `src/resume_agent/api/routers/auth.py`:

```python
"""Login/logout/me for the single-account session (spec 2026-07-10 §2).

Registered UNGUARDED: this router IS the credential check. /me never 401s —
the SPA auth gate polls it to decide whether to show the login page.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request, Response

from resume_agent.api import auth
from resume_agent.api.deps import get_settings_dep
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.auth import LoginRequest, MeResponse
from resume_agent.config import Settings

router = APIRouter(prefix="/auth", tags=["auth"])

# Fixed delay on failed logins: enough throttling for a single account.
# Module-level so tests can zero it.
FAILED_LOGIN_DELAY_SECONDS = 1.0


@router.post("/login")
def login(
    body: LoginRequest,
    response: Response,
    settings: Settings = Depends(get_settings_dep),
) -> MeResponse:
    if not auth.session_auth_configured(settings):
        raise ApiException(
            400, "AUTH_NOT_CONFIGURED", "Session auth is not configured"
        )
    ok = body.username == settings.auth_username and auth.verify_password(
        body.password, settings.auth_password_hash
    )
    if not ok:
        time.sleep(FAILED_LOGIN_DELAY_SECONDS)
        raise ApiException(401, "UNAUTHORIZED", "Invalid username or password")
    response.set_cookie(
        auth.SESSION_COOKIE,
        auth.issue_session(settings),
        max_age=auth.SESSION_LIFETIME_SECONDS,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    return MeResponse(username=body.username, auth_required=True)


@router.post("/logout")
def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return {"status": "ok"}


@router.get("/me")
def me(
    request: Request, settings: Settings = Depends(get_settings_dep)
) -> MeResponse:
    if not auth.session_auth_configured(settings):
        return MeResponse(username=None, auth_required=False)
    token = request.cookies.get(auth.SESSION_COOKIE)
    username = auth.verify_session(token, settings) if token else None
    return MeResponse(username=username, auth_required=True)
```

- [ ] **Step 5: Extend the guard and the settings refresh**

In `src/resume_agent/api/deps.py`, replace `require_token` (lines 26-47) with:

```python
def require_token(
    request: Request,
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings_dep),
) -> None:
    """Combined guard: session cookie OR static bearer token.

    Enforcement activates when either mechanism is configured; when neither is
    (local dev), it stays a no-op. The bearer keeps its query-param fallback for
    header-less clients (EventSource SSE, <a> downloads) — same-origin browser
    sessions don't need it (cookies ride along automatically).
    """
    from resume_agent.api.auth import (
        SESSION_COOKIE,
        session_auth_configured,
        verify_session,
    )

    session_configured = session_auth_configured(settings)
    if session_configured:
        cookie = request.cookies.get(SESSION_COOKIE)
        if cookie and verify_session(cookie, settings) is not None:
            return
    if settings.api_token:
        query_token = request.query_params.get("token")
        if query_token is not None and hmac.compare_digest(
            query_token, settings.api_token
        ):
            return
        expected = f"Bearer {settings.api_token}"
        if hmac.compare_digest(authorization or "", expected):
            return
        raise ApiException(401, "UNAUTHORIZED", "Missing or invalid credentials")
    if session_configured:
        raise ApiException(401, "UNAUTHORIZED", "Missing or invalid credentials")
```

In the same file, replace `refresh_app_settings` (lines 54-59) with:

```python
def refresh_app_settings(app, fresh: Settings) -> None:
    """Env-derived settings changed; keep startup-resolved and platform-managed
    values so a web-settings save can never lock the owner out mid-session."""
    app.state.settings = fresh.model_copy(update={
        "db_url": app.state.db_url,
        "api_token": app.state.settings.api_token,
        "auth_username": app.state.settings.auth_username,
        "auth_password_hash": app.state.settings.auth_password_hash,
        "session_secret": app.state.settings.session_secret,
    })
```

- [ ] **Step 6: Register the router**

In `src/resume_agent/api/app.py`: add to the router import block (~line 16):

```python
from resume_agent.api.routers import auth as auth_router
```

and register it UNGUARDED, directly after the health router (~line 119):

```python
    app.include_router(auth_router.router, prefix="/api")
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_auth_router.py tests/api/test_app_health.py -v`
Expected: all PASS (health tests prove open mode and bearer behavior unchanged).

- [ ] **Step 8: Regenerate the contract**

Run: `bash scripts/gen_ts_client.sh`
Expected: `Wrote contracts/ts/api.ts` and `Copied contract to web/src/lib/api/schema.ts`.

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -v`
Expected: PASS.

- [ ] **Step 9: Full suite + lint, then commit**

Run: `.venv/Scripts/python.exe -m pytest && ruff check`
Expected: all pass.

```bash
git add src/resume_agent/api/schemas/auth.py src/resume_agent/api/routers/auth.py src/resume_agent/api/deps.py src/resume_agent/api/app.py tests/api/test_auth_router.py contracts/openapi.json contracts/ts/api.ts web/src/lib/api/schema.ts
git commit -m "feat: session login endpoints + combined cookie-or-bearer guard"
```

---

### Task 3: Frontend login page + auth gate

**Files:**
- Create: `web/src/features/auth/LoginPage.tsx`
- Create: `web/src/features/auth/AuthGate.tsx`
- Create: `web/src/features/auth/LogoutButton.tsx`
- Create: `web/src/features/auth/auth.test.tsx`
- Modify: `web/src/lib/api/client.ts` (add a 401-redirect middleware after the existing `api.use` block)
- Modify: `web/src/app/router.tsx` (add `/login` route; wrap the AppLayout route in `AuthGate`)
- Modify: `web/src/app/AppLayout.tsx` (render `<LogoutButton />` in the nav)

**Interfaces:**
- Consumes (Task 2, via regenerated `web/src/lib/api/schema.ts`): `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me` returning `{username: string|null, authRequired: boolean}`.
- Consumes (existing): `api`, `unwrap` from `@/lib/api/client`; MSW `server` from `@/test/server`; test `wrap` pattern from `web/src/test/a11y.test.tsx`.
- Produces: `<AuthGate>{children}</AuthGate>` (redirects to `/login` when `authRequired && !username`), `<LoginPage />`, `<LogoutButton />` (renders nothing when auth is not required).

- [ ] **Step 1: Write the failing tests**

Create `web/src/features/auth/auth.test.tsx`:

```tsx
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "@/test/server";
import { AuthGate } from "./AuthGate";
import { LoginPage } from "./LoginPage";

const wrap = (ui: ReactNode, initialPath = "/") => {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/login" element={<div>login page</div>} />
          <Route path="/" element={<AuthGate>{ui}</AuthGate>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

describe("AuthGate", () => {
  it("renders children when auth is not required", async () => {
    server.use(
      http.get("/api/auth/me", () =>
        HttpResponse.json({ username: null, authRequired: false }),
      ),
    );
    wrap(<div>app content</div>);
    expect(await screen.findByText("app content")).toBeInTheDocument();
  });

  it("renders children when logged in", async () => {
    server.use(
      http.get("/api/auth/me", () =>
        HttpResponse.json({ username: "owner", authRequired: true }),
      ),
    );
    wrap(<div>app content</div>);
    expect(await screen.findByText("app content")).toBeInTheDocument();
  });

  it("redirects to /login when auth is required and no session", async () => {
    server.use(
      http.get("/api/auth/me", () =>
        HttpResponse.json({ username: null, authRequired: true }),
      ),
    );
    wrap(<div>app content</div>);
    expect(await screen.findByText("login page")).toBeInTheDocument();
  });
});

describe("LoginPage", () => {
  it("shows an error on rejected credentials", async () => {
    server.use(
      http.post("/api/auth/login", () =>
        HttpResponse.json(
          { error: { code: "UNAUTHORIZED", message: "Invalid username or password" } },
          { status: 401 },
        ),
      ),
    );
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter initialEntries={["/login"]}>
          <LoginPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    await userEvent.type(screen.getByLabelText(/username/i), "owner");
    await userEvent.type(screen.getByLabelText(/password/i), "wrong");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(
      await screen.findByText(/invalid username or password/i),
    ).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npm run test:run -- src/features/auth`
Expected: FAIL — cannot resolve `./AuthGate` / `./LoginPage`.

- [ ] **Step 3: Implement AuthGate**

Create `web/src/features/auth/AuthGate.tsx`:

```tsx
import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Navigate } from "react-router-dom";

import { api, unwrap } from "@/lib/api/client";

export function useMe() {
  return useQuery({
    queryKey: ["auth", "me"],
    queryFn: () => unwrap(api.GET("/api/auth/me")),
    staleTime: 60_000,
  });
}

/** Blocks the app shell until /api/auth/me answers; bounces to /login when a
 * session is required and absent. Renders nothing while loading (the page
 * skeletons behind it handle perceived latency). */
export function AuthGate({ children }: { children: ReactNode }) {
  const { data, isLoading } = useMe();
  if (isLoading) return null;
  if (data?.authRequired && !data.username) return <Navigate to="/login" replace />;
  return <>{children}</>;
}
```

- [ ] **Step 4: Implement LoginPage and LogoutButton**

Create `web/src/features/auth/LoginPage.tsx`:

```tsx
import { type FormEvent, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { api, unwrap } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const login = useMutation({
    mutationFn: () =>
      unwrap(api.POST("/api/auth/login", { body: { username, password } })),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
      navigate("/", { replace: true });
    },
  });

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    login.mutate();
  };

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <form onSubmit={onSubmit} className="w-full max-w-sm space-y-4">
        <h1 className="text-lg font-semibold">Resume Agent</h1>
        <div className="space-y-2">
          <Label htmlFor="login-username">Username</Label>
          <Input
            id="login-username"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="login-password">Password</Label>
          <Input
            id="login-password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </div>
        {login.isError && (
          <p role="alert" className="text-sm text-destructive">
            {login.error instanceof Error ? login.error.message : "Login failed"}
          </p>
        )}
        <Button type="submit" className="w-full" disabled={login.isPending}>
          {login.isPending ? "Signing in…" : "Sign in"}
        </Button>
      </form>
    </div>
  );
}
```

Note: `Button`/`Input`/`Label` are the existing shadcn components under `web/src/components/ui/`. If a name differs (check the directory), use the local equivalent — do not add new UI deps.

Create `web/src/features/auth/LogoutButton.tsx`:

```tsx
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { LogOut } from "lucide-react";

import { api, unwrap } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import { useMe } from "./AuthGate";

/** Renders nothing in open (no-auth) mode. */
export function LogoutButton() {
  const { data } = useMe();
  const queryClient = useQueryClient();
  const logout = useMutation({
    mutationFn: () => unwrap(api.POST("/api/auth/logout")),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["auth", "me"] }),
  });
  if (!data?.authRequired) return null;
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={() => logout.mutate()}
      aria-label="Sign out"
    >
      <LogOut className="size-4" />
    </Button>
  );
}
```

- [ ] **Step 5: Wire the router, layout, and 401 middleware**

In `web/src/app/router.tsx`:
1. Add imports: `import { AuthGate } from "@/features/auth/AuthGate";` and a lazy login page alongside the other lazy pages:
```tsx
const LoginPage = lazy(() =>
  import("@/features/auth/LoginPage").then((m) => ({ default: m.LoginPage })),
);
```
2. In the route array, add a top-level sibling of the AppLayout route (wrap the
lazy element in `Suspense` exactly the way the file's existing routes do; if the
file has a wrapping helper, use it, otherwise inline):
```tsx
  {
    path: "/login",
    element: (
      <Suspense fallback={null}>
        <LoginPage />
      </Suspense>
    ),
  },
```
3. Wrap the AppLayout route element: where the root route renders `<AppLayout />` (possibly inside `SetupGate`), wrap the outermost element in `<AuthGate>…</AuthGate>` so auth is checked before setup.

In `web/src/app/AppLayout.tsx`: import `LogoutButton` and render `<LogoutButton />` in the nav/header area (next to the theme toggle if present).

In `web/src/lib/api/client.ts`, after the existing `api.use({ onRequest … })` block, add:

```ts
api.use({
  onResponse({ response }) {
    // A 401 anywhere means the session died (expired cookie, rotated secret).
    // Bounce to the login page — except when already on it (login's own 401).
    if (
      response.status === 401 &&
      typeof window !== "undefined" &&
      window.location.pathname !== "/login"
    ) {
      window.location.assign("/login");
    }
    return response;
  },
});
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd web && npm run test:run -- src/features/auth`
Expected: all PASS.

- [ ] **Step 7: Full frontend gates, then commit**

Run: `cd web && npm run test:run && npm run lint && npm run build`
Expected: tests pass, lint clean, `tsc -b && vite build` succeeds.

```bash
git add web/src/features/auth web/src/app/router.tsx web/src/app/AppLayout.tsx web/src/lib/api/client.ts
git commit -m "feat: login page, auth gate, logout, 401 redirect in SPA"
```

---

### Task 4: `browser_enabled` degradation

**Files:**
- Modify: `src/resume_agent/discovery/connectors/companies.py` (new exception ~line 31; `_failure_reason` ~line 129; `__init__` ~line 151; `_produce` ~line 181)
- Modify: `src/resume_agent/discovery/connectors/registry.py` (companies/scrape/adzuna/linkedin specs, lines 60-103)
- Modify: `src/resume_agent/services/discovery.py` (`add_job_from_url` ~line 103)
- Test: `tests/test_browser_capability.py`

**Interfaces:**
- Consumes (Task 1): `Settings.browser_enabled`.
- Produces:
  - `companies.BrowserRequired(Exception)`
  - `CompaniesConnector(urls, *, browser_enabled: bool = True)` — Tesla units fail with reason `"requires a local browser (browser_enabled=false)"` when disabled.
  - Registry: `scrape` and `linkedin` specs get `pullable=lambda s: s.browser_enabled`; `adzuna` build passes `enrich_details=s.browser_enabled`; `companies` build passes `browser_enabled=s.browser_enabled`.
  - `add_job_from_url` ANDs its `allow_browser` arg with `get_settings().browser_enabled`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_browser_capability.py`:

```python
"""browser_enabled=False degrades browser connectors honestly (spec §4)."""

from resume_agent.config import Settings
from resume_agent.discovery.connectors import companies as companies_mod
from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.companies import CompaniesConnector
from resume_agent.discovery.connectors.config import ConnectorsConfig
from resume_agent.discovery.connectors.registry import build_connectors
from resume_agent.discovery.search_config import SearchConfig

_SEARCH = SearchConfig()  # no anchors: relevance gate falls through


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **kw)


def _config() -> ConnectorsConfig:
    return ConnectorsConfig.model_validate(
        {
            "scrape": {"enabled": True, "targets": [{"url": "https://x.example/jobs"}]},
            "linkedin": {"enabled": True},
            "adzuna": {"enabled": True},
            "companies": {"enabled": True, "urls": [{"url": "https://boards.greenhouse.io/acme"}]},
        }
    )


def test_registry_drops_scrape_and_linkedin_when_browser_disabled():
    kinds = {
        type(c).__name__
        for c in build_connectors(
            _config(),
            _settings(browser_enabled=False, adzuna_app_id="i", adzuna_app_key="k"),
        )
    }
    assert "DashboardScraper" not in kinds
    assert all("LinkedIn" not in k and "Scraper" not in k for k in kinds)


def test_registry_adzuna_snippet_only_when_browser_disabled():
    connectors = build_connectors(
        _config(),
        _settings(browser_enabled=False, adzuna_app_id="i", adzuna_app_key="k"),
    )
    adzuna = next(c for c in connectors if type(c).__name__ == "AdzunaConnector")
    assert adzuna.enrich_details is False


def test_registry_adzuna_enriches_when_browser_enabled():
    connectors = build_connectors(
        _config(),
        _settings(browser_enabled=True, adzuna_app_id="i", adzuna_app_key="k"),
    )
    adzuna = next(c for c in connectors if type(c).__name__ == "AdzunaConnector")
    assert adzuna.enrich_details is True


def test_companies_tesla_recorded_as_failure_when_browser_disabled(monkeypatch):
    ghjob = RawJob(
        source="greenhouse", url="https://boards.greenhouse.io/acme/jobs/1",
        company="Acme", title="Engineer", location="", jd_text="",
    )
    monkeypatch.setitem(
        companies_mod._BACKENDS, "greenhouse",
        lambda target, search, limit=None, skip_seen=None: [ghjob],
    )
    conn = CompaniesConnector(
        ["https://www.tesla.com/careers/search", "https://boards.greenhouse.io/acme"],
        browser_enabled=False,
    )
    result = conn.fetch(_SEARCH)
    assert result.failures == {
        "https://www.tesla.com/careers/search":
            "requires a local browser (browser_enabled=false)"
    }
    assert [j.url for j in result.jobs] == ["https://boards.greenhouse.io/acme/jobs/1"]


def test_companies_tesla_untouched_when_browser_enabled(monkeypatch):
    calls: list[str] = []
    monkeypatch.setitem(
        companies_mod._BACKENDS, "tesla",
        lambda target, search, limit=None, skip_seen=None: calls.append("tesla") or [],
    )
    conn = CompaniesConnector(
        ["https://www.tesla.com/careers/search"], browser_enabled=True
    )
    result = conn.fetch(_SEARCH)
    assert calls == ["tesla"]
    assert result.failures == {}


def test_add_job_from_url_gates_browser(monkeypatch):
    from resume_agent.services import discovery as discovery_mod

    seen: dict[str, bool] = {}

    def fake_job_from_url(url, *, agent, allow_browser=True):
        seen["allow_browser"] = allow_browser
        return None

    monkeypatch.setattr(discovery_mod, "job_from_url", fake_job_from_url)
    monkeypatch.setattr(discovery_mod, "build_url_extract_agent", lambda: object())
    monkeypatch.setattr(
        discovery_mod, "get_settings", lambda: _settings(browser_enabled=False)
    )
    try:
        discovery_mod.add_job_from_url(None, url="https://x.example/j/1")
    except discovery_mod.UrlFetchError:
        pass
    assert seen["allow_browser"] is False
```

Note: if `SearchConfig()` requires arguments or `ConnectorsConfig.model_validate` needs different section shapes, mirror the fixtures already used in `tests/test_discovery_ingest.py` / existing connector tests rather than inventing new shapes. If `services/discovery.py` does not already import `get_settings`, the last test's monkeypatch target is added in Step 5.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_browser_capability.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'browser_enabled'` (and registry/adzuna assertions fail).

- [ ] **Step 3: Gate Tesla inside CompaniesConnector**

In `src/resume_agent/discovery/connectors/companies.py`:

Add after `UnsupportedAts` (~line 41):

```python
class BrowserRequired(Exception):
    """The URL's backend needs a visible local browser, disabled on this instance."""
```

Add a branch in `_failure_reason` (~line 135, before the `httpx.HTTPError` check):

```python
    if isinstance(exc, BrowserRequired):
        return "requires a local browser (browser_enabled=false)"
```

Change `__init__` (~line 151):

```python
    def __init__(self, urls: list[CompanyUrl | str], *, browser_enabled: bool = True):
        self.browser_enabled = browser_enabled
        self.urls = [
            CompanyUrl(url=entry) if isinstance(entry, str) else entry for entry in urls
        ]
```

In `_produce`, after the `backend is None` check (~line 193):

```python
        if target.ats == "tesla" and not self.browser_enabled:
            raise BrowserRequired
```

- [ ] **Step 4: Wire settings through the registry**

In `src/resume_agent/discovery/connectors/registry.py`:

- companies spec (~line 66): `build=lambda payloads, c, s: CompaniesConnector(payloads, browser_enabled=s.browser_enabled),`
- scrape spec (~line 74): add `pullable=lambda s: s.browser_enabled,` after `build`.
- adzuna spec (~line 88): add `enrich_details=s.browser_enabled,` to the `AdzunaConnector(...)` call (keep the existing `pullable` key check AND-ed: `pullable=lambda s: bool(s.adzuna_app_id and s.adzuna_app_key)` stays as-is — enrichment is what degrades, not the API pull).
- linkedin spec (~line 100): add `pullable=lambda s: s.browser_enabled,`.

- [ ] **Step 5: Gate URL-ingest at the service**

In `src/resume_agent/services/discovery.py`, inside `add_job_from_url` (~line 110), change the `job_from_url(...)` call to AND the caller's flag with settings (add `from resume_agent.config import get_settings` to the imports if absent):

```python
        raw = job_from_url(
            url,
            agent=build_url_extract_agent(),
            allow_browser=allow_browser and get_settings().browser_enabled,
        )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_browser_capability.py -v`
Expected: all PASS.

- [ ] **Step 7: Full suite + lint, then commit**

Run: `.venv/Scripts/python.exe -m pytest && ruff check`
Expected: all pass (existing connector tests confirm `browser_enabled=True` default changes nothing).

```bash
git add src/resume_agent/discovery/connectors/companies.py src/resume_agent/discovery/connectors/registry.py src/resume_agent/services/discovery.py tests/test_browser_capability.py
git commit -m "feat: browser_enabled flag degrades browser connectors per-unit"
```

---

### Task 5: `prepare_data_root` + container entrypoint

**Files:**
- Create: `src/resume_agent/deploy.py`
- Create: `docker/entrypoint.sh`
- Test: `tests/test_deploy_prepare.py`

**Interfaces:**
- Consumes: nothing from other tasks (pure filesystem).
- Produces (used by Task 8's Dockerfile):
  - `prepare_data_root(app_root: Path, data_root: Path, defaults_dir: Path | None = None) -> None`
  - `python -m resume_agent.deploy` entrypoint honoring `APP_ROOT` (default `/app`) and `DATA_ROOT` (default `$APP_ROOT/data`), seeding config from `$APP_ROOT/config.defaults`.
  - `LINKS: dict[str, str]` mapping app-root names to data-root targets (`output`, `config`, `.env`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_deploy_prepare.py`:

```python
"""Volume prep: seed defaults + symlink mutable paths (spec §3, ADR 0002).

Symlink creation needs privileges on Windows (Developer Mode enables it);
tests probe and skip rather than fail on locked-down machines.
"""

import pytest

from resume_agent.deploy import prepare_data_root


def _require_symlinks(tmp_path):
    probe = tmp_path / "_probe"
    try:
        probe.symlink_to(tmp_path)
    except OSError:
        pytest.skip("symlinks unavailable (enable Windows Developer Mode)")
    probe.unlink()


def _roots(tmp_path):
    app_root = tmp_path / "app"
    app_root.mkdir()
    defaults = app_root / "config.defaults"
    defaults.mkdir()
    (defaults / "search.yaml").write_text("titles: []\n", encoding="utf-8")
    return app_root, app_root / "data", defaults


def test_fresh_boot_seeds_and_links(tmp_path):
    _require_symlinks(tmp_path)
    app_root, data_root, defaults = _roots(tmp_path)
    prepare_data_root(app_root, data_root, defaults_dir=defaults)
    assert (data_root / "config" / "search.yaml").read_text(encoding="utf-8") == "titles: []\n"
    assert (data_root / "output").is_dir()
    assert (data_root / ".env").is_file()
    for name in ("output", "config", ".env"):
        assert (app_root / name).is_symlink()
    # writes through the link land on the volume
    (app_root / "config" / "extra.yaml").write_text("a: 1\n", encoding="utf-8")
    assert (data_root / "config" / "extra.yaml").is_file()


def test_second_boot_is_idempotent_and_preserves_edits(tmp_path):
    _require_symlinks(tmp_path)
    app_root, data_root, defaults = _roots(tmp_path)
    prepare_data_root(app_root, data_root, defaults_dir=defaults)
    (data_root / "config" / "search.yaml").write_text("titles: [edited]\n", encoding="utf-8")
    (data_root / ".env").write_text("ANTHROPIC_API_KEY=sk-x\n", encoding="utf-8")
    prepare_data_root(app_root, data_root, defaults_dir=defaults)  # redeploy
    assert (data_root / "config" / "search.yaml").read_text(encoding="utf-8") == "titles: [edited]\n"
    assert (data_root / ".env").read_text(encoding="utf-8") == "ANTHROPIC_API_KEY=sk-x\n"


def test_refuses_to_shadow_a_real_path(tmp_path):
    _require_symlinks(tmp_path)
    app_root, data_root, defaults = _roots(tmp_path)
    (app_root / "config").mkdir()  # a real dir, e.g. accidentally baked into the image
    with pytest.raises(RuntimeError, match="refusing to shadow"):
        prepare_data_root(app_root, data_root, defaults_dir=defaults)


def test_no_defaults_dir_still_creates_structure(tmp_path):
    _require_symlinks(tmp_path)
    app_root = tmp_path / "app"
    app_root.mkdir()
    data_root = app_root / "data"
    prepare_data_root(app_root, data_root, defaults_dir=None)
    assert (data_root / "config").is_dir()
    assert (data_root / "output").is_dir()
    assert (data_root / ".env").is_file()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_deploy_prepare.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.deploy'` (or SKIP everywhere if symlinks are unavailable — in that case enable Windows Developer Mode or accept container-only coverage, and say so in the commit message).

- [ ] **Step 3: Implement `src/resume_agent/deploy.py`**

```python
"""Container boot: bring every mutable path onto the Data root volume.

Railway allows one volume per service (mounted at DATA_ROOT). The app has four
mutable roots — data/, output/, config/, .env — so the entrypoint symlinks the
other three into the volume before serving (ADR 0002 / spec §3). Idempotent:
a redeploy never overwrites volume content.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

# app-root name -> path under the data root
LINKS: dict[str, str] = {"output": "output", "config": "config", ".env": ".env"}


def prepare_data_root(
    app_root: Path, data_root: Path, defaults_dir: Path | None = None
) -> None:
    data_root.mkdir(parents=True, exist_ok=True)
    config_dst = data_root / "config"
    if defaults_dir is not None and defaults_dir.is_dir() and not config_dst.exists():
        shutil.copytree(defaults_dir, config_dst)
    config_dst.mkdir(exist_ok=True)
    (data_root / "output").mkdir(exist_ok=True)
    env_file = data_root / ".env"
    if not env_file.exists():
        env_file.touch()
    for name, target in LINKS.items():
        link = app_root / name
        if link.is_symlink():
            continue
        if link.exists():
            raise RuntimeError(
                f"{link} already exists and is not a symlink; refusing to shadow it"
            )
        link.symlink_to(data_root / target)


def main() -> None:
    app_root = Path(os.environ.get("APP_ROOT", "/app"))
    data_root = Path(os.environ.get("DATA_ROOT", str(app_root / "data")))
    prepare_data_root(app_root, data_root, defaults_dir=app_root / "config.defaults")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_deploy_prepare.py -v`
Expected: all PASS (or SKIP with the documented reason).

- [ ] **Step 5: Write the entrypoint**

Create `docker/entrypoint.sh` (LF line endings — add a `.gitattributes` rule if needed: `docker/entrypoint.sh text eol=lf`):

```sh
#!/bin/sh
set -e
python -m resume_agent.deploy
exec resume-agent serve --host 0.0.0.0 --port "${PORT:-8000}"
```

- [ ] **Step 6: Full suite + lint, then commit**

Run: `.venv/Scripts/python.exe -m pytest && ruff check`
Expected: all pass.

```bash
git add src/resume_agent/deploy.py docker/entrypoint.sh tests/test_deploy_prepare.py .gitattributes
git commit -m "feat: volume prep (seed + symlinks) and container entrypoint"
```

---

### Task 6: Whole-root export/import — service + admin router

**Files:**
- Create: `src/resume_agent/services/backup.py`
- Create: `src/resume_agent/api/routers/admin.py`
- Modify: `src/resume_agent/api/app.py` (import block ~line 16, guarded registration ~line 135)
- Modify (generated): `contracts/openapi.json`, `contracts/ts/api.ts`, `web/src/lib/api/schema.ts`
- Test: `tests/test_backup_service.py`, `tests/api/test_admin_backup.py`

**Interfaces:**
- Consumes: `app.state.data_dir`, `app.state.db_url`, `app.state.engine`, `app.state.env_path`, `RunManager.list_active()`, `refresh_app_settings` (Task 2 version), `make_engine`/`init_db` (`resume_agent.db`).
- Produces (used by Task 7):
  - `backup.sqlite_snapshot(db_file: Path, dest: Path) -> None`
  - `backup.export_data_root(data_root: Path, db_url: str, out_dir: Path) -> Path` (returns the archive path)
  - `backup.import_data_root(archive: Path, data_root: Path) -> None`
  - `backup.UnsafeArchiveError(ValueError)`
  - `GET /api/admin/export` (409 `RUNS_ACTIVE` while runs active), `POST /api/admin/import?confirm=REPLACE` (400 `CONFIRM_REQUIRED` without it; 400 `UNSAFE_ARCHIVE` on traversal; 409 while runs active).

- [ ] **Step 1: Write the failing service tests**

Create `tests/test_backup_service.py`:

```python
"""Whole-root tarball export/import (spec §5, ADR 0002)."""

import sqlite3
import tarfile

import pytest

from resume_agent.services.backup import (
    UnsafeArchiveError,
    export_data_root,
    import_data_root,
    sqlite_snapshot,
)


def _make_root(tmp_path, name="data"):
    root = tmp_path / name
    (root / "profile").mkdir(parents=True)
    (root / "profile" / "facts.json").write_text('{"facts": []}', encoding="utf-8")
    (root / ".env").write_text("ANTHROPIC_API_KEY=sk-x\n", encoding="utf-8")
    db = root / "resume_agent.db"
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE job (id INTEGER PRIMARY KEY, title TEXT)")
        conn.execute("INSERT INTO job (title) VALUES ('Engineer')")
    conn.close()
    return root, db


def test_sqlite_snapshot_is_consistent_copy(tmp_path):
    _, db = _make_root(tmp_path)
    dest = tmp_path / "snap.db"
    sqlite_snapshot(db, dest)
    with sqlite3.connect(dest) as conn:
        assert conn.execute("SELECT title FROM job").fetchall() == [("Engineer",)]
    conn.close()


def test_export_replaces_live_db_with_snapshot(tmp_path):
    root, db = _make_root(tmp_path)
    (root / "resume_agent.db-wal").write_bytes(b"")  # simulate a live WAL sidecar
    archive = export_data_root(root, f"sqlite:///{db.as_posix()}", tmp_path / "out")
    with tarfile.open(archive) as tar:
        names = tar.getnames()
    assert "profile/facts.json" in names
    assert ".env" in names
    assert "resume_agent.db" in names
    assert "resume_agent.db-wal" not in names  # sidecars never ship


def test_roundtrip_restores_content(tmp_path):
    root, db = _make_root(tmp_path)
    archive = export_data_root(root, f"sqlite:///{db.as_posix()}", tmp_path / "out")
    # mutate after export
    (root / "profile" / "facts.json").write_text('{"facts": ["junk"]}', encoding="utf-8")
    (root / "stray.txt").write_text("x", encoding="utf-8")
    import_data_root(archive, root)
    assert (root / "profile" / "facts.json").read_text(encoding="utf-8") == '{"facts": []}'
    assert not (root / "stray.txt").exists()  # full replace, not merge
    with sqlite3.connect(root / "resume_agent.db") as conn:
        assert conn.execute("SELECT title FROM job").fetchall() == [("Engineer",)]
    conn.close()


def test_import_rejects_traversal_before_touching_root(tmp_path):
    root, _ = _make_root(tmp_path)
    evil = tmp_path / "evil.tar.gz"
    payload = tmp_path / "payload.txt"
    payload.write_text("pwned", encoding="utf-8")
    with tarfile.open(evil, "w:gz") as tar:
        tar.add(payload, arcname="../escape.txt")
    with pytest.raises(UnsafeArchiveError):
        import_data_root(evil, root)
    # validation failed BEFORE the wipe: the root is intact
    assert (root / "profile" / "facts.json").exists()


def test_export_db_outside_root_ships_tree_only(tmp_path):
    root, _ = _make_root(tmp_path)
    archive = export_data_root(root, "sqlite:///elsewhere/other.db", tmp_path / "out")
    with tarfile.open(archive) as tar:
        assert "profile/facts.json" in tar.getnames()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_backup_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'resume_agent.services.backup'`

- [ ] **Step 3: Implement `src/resume_agent/services/backup.py`**

```python
"""Whole-root export/import (ADR 0002): the Data root moves as one tarball.

Export replaces the live WAL-mode SQLite file with a `VACUUM INTO` snapshot so
the archive never contains a torn .db/-wal pair. Import validates every member
BEFORE wiping the root (fail-closed), then full-replaces the tree — never a
merge.
"""

from __future__ import annotations

import shutil
import sqlite3
import tarfile
import tempfile
from datetime import date
from pathlib import Path


class UnsafeArchiveError(ValueError):
    """Archive member escapes the data root or has an unsupported type."""


def sqlite_snapshot(db_file: Path, dest: Path) -> None:
    """Consistent copy of a (possibly live, WAL-mode) SQLite DB."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_file)
    try:
        conn.execute("VACUUM INTO ?", (str(dest),))
    finally:
        conn.close()


def _sqlite_file(db_url: str, data_root: Path) -> Path | None:
    """The DB file path, only when file-backed AND inside the data root."""
    prefix = "sqlite:///"
    if not db_url.startswith(prefix) or db_url.endswith(":memory:"):
        return None
    db_file = Path(db_url[len(prefix):]).resolve()
    return db_file if db_file.is_relative_to(data_root.resolve()) else None


def _is_db_artifact(path: Path, db_file: Path) -> bool:
    return path.name in (db_file.name, f"{db_file.name}-wal", f"{db_file.name}-shm") \
        and path.parent.resolve() == db_file.parent.resolve()


def export_data_root(data_root: Path, db_url: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / f"resume-agent-data-{date.today().isoformat()}.tar.gz"
    db_file = _sqlite_file(db_url, data_root)
    with tempfile.TemporaryDirectory() as tmp:
        snapshot: Path | None = None
        if db_file is not None and db_file.exists():
            snapshot = Path(tmp) / db_file.name
            sqlite_snapshot(db_file, snapshot)
        with tarfile.open(archive, "w:gz") as tar:
            for path in sorted(data_root.rglob("*")):
                if db_file is not None and _is_db_artifact(path, db_file):
                    continue
                tar.add(path, arcname=path.relative_to(data_root).as_posix(),
                        recursive=False)
            if snapshot is not None:
                assert db_file is not None
                tar.add(snapshot,
                        arcname=db_file.relative_to(data_root.resolve()).as_posix())
    return archive


def _validate_member(member: tarfile.TarInfo) -> None:
    parts = Path(member.name).parts
    if member.name.startswith(("/", "\\")) or ".." in parts:
        raise UnsafeArchiveError(f"unsafe path in archive: {member.name}")
    if not (member.isfile() or member.isdir()):
        raise UnsafeArchiveError(f"unsupported member type: {member.name}")


def import_data_root(archive: Path, data_root: Path) -> None:
    """Full-replace the Data root from a tarball. Destructive; caller gates it."""
    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / "staged"
        staged.mkdir()
        with tarfile.open(archive, "r:gz") as tar:
            for member in tar.getmembers():
                _validate_member(member)
            tar.extractall(staged, filter="data")
        for child in list(data_root.iterdir()):
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        for child in list(staged.iterdir()):
            shutil.move(str(child), str(data_root / child.name))
```

- [ ] **Step 4: Run service tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_backup_service.py -v`
Expected: all PASS.

- [ ] **Step 5: Write the failing router tests**

Create `tests/api/test_admin_backup.py`:

```python
"""Admin export/import endpoints: gates + engine swap (spec §5)."""

import io

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from resume_agent.api.app import create_app
from resume_agent.tracking.tables import Job


def _app(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "profile").mkdir()
    (data_dir / "profile" / "facts.json").write_text("{}", encoding="utf-8")
    db_url = f"sqlite:///{(data_dir / 'resume_agent.db').as_posix()}"
    return create_app(db_url=db_url, data_dir=data_dir), data_dir


def _add_job(app, title="Engineer"):
    with Session(app.state.engine) as session:
        session.add(Job(company="Acme", title=title, url="https://x/1", jd_text="jd"))
        session.commit()


def test_export_then_import_restores_state(tmp_path):
    app, _ = _app(tmp_path)
    with TestClient(app) as client:
        _add_job(app, "Engineer")
        exported = client.get("/api/admin/export")
        assert exported.status_code == 200
        assert exported.headers["content-type"] == "application/gzip"
        _add_job(app, "Mutation After Export")
        resp = client.post(
            "/api/admin/import?confirm=REPLACE",
            files={"file": ("data.tar.gz", io.BytesIO(exported.content))},
        )
        assert resp.status_code == 200
        with Session(app.state.engine) as session:
            titles = session.exec(select(Job.title)).all()
        assert titles == ["Engineer"]  # post-export mutation gone: full replace


def test_import_requires_confirm(tmp_path):
    app, _ = _app(tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/api/admin/import",
            files={"file": ("data.tar.gz", io.BytesIO(b"x"))},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == "CONFIRM_REQUIRED"


def test_endpoints_refuse_while_runs_active(tmp_path, monkeypatch):
    app, _ = _app(tmp_path)
    with TestClient(app) as client:
        monkeypatch.setattr(
            app.state.run_manager, "list_active", lambda: [object()]
        )
        assert client.get("/api/admin/export").status_code == 409
        resp = client.post(
            "/api/admin/import?confirm=REPLACE",
            files={"file": ("data.tar.gz", io.BytesIO(b"x"))},
        )
        assert resp.status_code == 409


def test_admin_guarded_like_other_routes(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_url = f"sqlite:///{(data_dir / 'resume_agent.db').as_posix()}"
    app = create_app(db_url=db_url, data_dir=data_dir, api_token="secret")
    with TestClient(app) as client:
        assert client.get("/api/admin/export").status_code == 401
```

Note: check `Job`'s required fields in `src/resume_agent/tracking/tables.py` before running; adjust `_add_job` to satisfy NOT NULL columns the same way existing tests (e.g. `tests/api/test_boards.py`) construct jobs.

- [ ] **Step 6: Run router tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_admin_backup.py -v`
Expected: FAIL — 404s (`No route for /api/admin/export`).

- [ ] **Step 7: Implement the router and register it**

Create `src/resume_agent/api/routers/admin.py`:

```python
"""Whole-root export/import endpoints (ADR 0002).

Import is destructive by design: it requires the literal ?confirm=REPLACE and
refuses while runs are active. Export refuses during runs too (artifacts may be
mid-write) and streams a WAL-safe archive that includes Operational secrets —
backups are secret material.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from resume_agent.api.deps import refresh_app_settings
from resume_agent.api.errors import ApiException
from resume_agent.config import Settings
from resume_agent.db import init_db, make_engine
from resume_agent.services.backup import (
    UnsafeArchiveError,
    export_data_root,
    import_data_root,
)

router = APIRouter(prefix="/admin", tags=["admin"])


def _refuse_if_running(request: Request) -> None:
    if request.app.state.run_manager.list_active():
        raise ApiException(
            409, "RUNS_ACTIVE", "Refusing while background runs are active"
        )


@router.get("/export")
def export_root(request: Request) -> FileResponse:
    _refuse_if_running(request)
    data_root: Path = request.app.state.data_dir
    tmp = Path(tempfile.mkdtemp(prefix="ra-export-"))
    archive = export_data_root(data_root, request.app.state.db_url, tmp)
    return FileResponse(
        archive,
        media_type="application/gzip",
        filename=archive.name,
        background=BackgroundTask(shutil.rmtree, tmp, ignore_errors=True),
    )


@router.post("/import")
def import_root(request: Request, file: UploadFile, confirm: str = "") -> dict[str, str]:
    if confirm != "REPLACE":
        raise ApiException(
            400, "CONFIRM_REQUIRED",
            "Import replaces the entire data root; pass ?confirm=REPLACE",
        )
    _refuse_if_running(request)
    data_root: Path = request.app.state.data_dir
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "import.tar.gz"
        with archive.open("wb") as fh:
            shutil.copyfileobj(file.file, fh)
        # Drop pooled connections so the SQLite file can be replaced; the
        # engine reconnects lazily, so a failed validation leaves it usable.
        request.app.state.engine.dispose()
        try:
            import_data_root(archive, data_root)
        except UnsafeArchiveError as exc:
            raise ApiException(400, "UNSAFE_ARCHIVE", str(exc))
    engine = make_engine(request.app.state.db_url)
    init_db(engine)
    request.app.state.engine = engine
    # the imported .env may carry different operational secrets
    refresh_app_settings(request.app, Settings(_env_file=request.app.state.env_path))
    return {"status": "imported"}
```

In `src/resume_agent/api/app.py`: add to the import block (~line 16):

```python
from resume_agent.api.routers import admin as admin_router
```

and register it in the guarded list (after the dashboard router, ~line 135):

```python
    app.include_router(admin_router.router, prefix="/api", dependencies=guarded)
```

- [ ] **Step 8: Run router tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_admin_backup.py -v`
Expected: all PASS.

- [ ] **Step 9: Regenerate the contract**

Run: `bash scripts/gen_ts_client.sh`
Then: `.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -v`
Expected: PASS.

- [ ] **Step 10: Full suite + lint, then commit**

Run: `.venv/Scripts/python.exe -m pytest && ruff check`
Expected: all pass.

```bash
git add src/resume_agent/services/backup.py src/resume_agent/api/routers/admin.py src/resume_agent/api/app.py tests/test_backup_service.py tests/api/test_admin_backup.py contracts/openapi.json contracts/ts/api.ts web/src/lib/api/schema.ts
git commit -m "feat: whole-root export/import service + admin endpoints"
```

---

### Task 7: Local seed packer (`pack_local_checkout` + script)

**Files:**
- Modify: `src/resume_agent/services/backup.py` (append one function)
- Create: `scripts/pack_data.py`
- Test: `tests/test_backup_service.py` (append tests)

**Interfaces:**
- Consumes (Task 6): `sqlite_snapshot`.
- Produces: `backup.pack_local_checkout(repo_root: Path, out: Path) -> Path` — tars the local checkout's `data/*` (at archive root, DB via snapshot), `config/` → `config/`, `output/` → `output/`, `.env` → `.env`, i.e. exactly the volume layout `POST /api/admin/import` expects.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_backup_service.py`:

```python
def test_pack_local_checkout_builds_volume_layout(tmp_path):
    from resume_agent.services.backup import pack_local_checkout

    repo = tmp_path / "repo"
    (repo / "data" / "profile").mkdir(parents=True)
    (repo / "data" / "profile" / "facts.json").write_text("{}", encoding="utf-8")
    db = repo / "data" / "resume_agent.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE job (id INTEGER PRIMARY KEY)")
    conn.close()
    (repo / "config").mkdir()
    (repo / "config" / "search.yaml").write_text("titles: []\n", encoding="utf-8")
    (repo / "output" / "acme").mkdir(parents=True)
    (repo / "output" / "acme" / "resume.pdf").write_bytes(b"%PDF")
    (repo / ".env").write_text("ANTHROPIC_API_KEY=sk-x\n", encoding="utf-8")

    archive = pack_local_checkout(repo, tmp_path / "seed.tar.gz")
    with tarfile.open(archive) as tar:
        names = set(tar.getnames())
    assert "profile/facts.json" in names        # data/* lands at archive root
    assert "resume_agent.db" in names
    assert "config/search.yaml" in names
    assert "output/acme/resume.pdf" in names
    assert ".env" in names


def test_pack_local_checkout_tolerates_missing_optional_paths(tmp_path):
    from resume_agent.services.backup import pack_local_checkout

    repo = tmp_path / "repo"
    (repo / "data").mkdir(parents=True)  # no config/, output/, .env
    archive = pack_local_checkout(repo, tmp_path / "seed.tar.gz")
    with tarfile.open(archive) as tar:
        assert tar.getnames() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_backup_service.py -k pack_local -v`
Expected: FAIL — `ImportError: cannot import name 'pack_local_checkout'`

- [ ] **Step 3: Implement**

Append to `src/resume_agent/services/backup.py`:

```python
def pack_local_checkout(repo_root: Path, out: Path) -> Path:
    """Tar the local checkout's mutable state in the VOLUME layout: data/* at
    the archive root (DB via snapshot), plus config/, output/, and .env beside
    it — exactly what POST /api/admin/import expects (spec §5 seed workflow)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    data_dir = repo_root / "data"
    with tempfile.TemporaryDirectory() as tmp, tarfile.open(out, "w:gz") as tar:
        if data_dir.is_dir():
            for path in sorted(data_dir.rglob("*")):
                rel = path.relative_to(data_dir)
                if path.suffix == ".db" and path.is_file():
                    snapshot = Path(tmp) / path.name
                    sqlite_snapshot(path, snapshot)
                    tar.add(snapshot, arcname=rel.as_posix())
                    continue
                if path.name.endswith((".db-wal", ".db-shm")):
                    continue
                tar.add(path, arcname=rel.as_posix(), recursive=False)
        for name in ("config", "output"):
            src = repo_root / name
            if src.is_dir():
                tar.add(src, arcname=name)
        env = repo_root / ".env"
        if env.is_file():
            tar.add(env, arcname=".env")
    return out
```

Create `scripts/pack_data.py`:

```python
"""Pack this checkout's data/, config/, output/, .env into a seed tarball.

Usage:
    .venv/Scripts/python.exe scripts/pack_data.py [--out seed.tar.gz]

Seed the deployed instance (after logging in via the web UI once to get a
session cookie, or using the API token):
    curl -H "Authorization: Bearer $API_TOKEN" -F "file=@seed.tar.gz" \
         "https://<your-app>.up.railway.app/api/admin/import?confirm=REPLACE"
"""

import argparse
from pathlib import Path

from resume_agent.services.backup import pack_local_checkout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="seed.tar.gz", type=Path)
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    archive = pack_local_checkout(repo_root, args.out)
    print(f"Wrote {archive} — treat it as secret material (.env is inside).")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/Scripts/python.exe -m pytest tests/test_backup_service.py -v`
Expected: all PASS.

- [ ] **Step 5: Full suite + lint, then commit**

Run: `.venv/Scripts/python.exe -m pytest && ruff check`
Expected: all pass.

```bash
git add src/resume_agent/services/backup.py scripts/pack_data.py tests/test_backup_service.py
git commit -m "feat: pack_local_checkout seed tarball + pack_data script"
```

---

### Task 8: Dockerfile, railway.json, runbook

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`
- Create: `railway.json`
- Create: `docs/deploy-railway.md`

**Interfaces:**
- Consumes: `docker/entrypoint.sh` + `python -m resume_agent.deploy` (Task 5), `resume-agent serve --host --port` (`cli.py:820`), `spa_dist_dir()` expecting `<repo_root>/web/dist` (`api/app.py:40-45`), `/api/health` (unauthenticated).
- Produces: a deployable image + Railway config-as-code + the operator runbook.

- [ ] **Step 1: Write `.dockerignore`**

```
.git
.venv
.omc
.remember
data
output
seed.tar.gz
web/node_modules
web/dist
web/test-results
tests
evals
docs
node_modules
__pycache__
*.pyc
.env
```

(`config/` is NOT ignored — the image copies it to `config.defaults/` for first-boot seeding. `.env` IS ignored — secrets never bake into the image.)

- [ ] **Step 2: Write the Dockerfile**

```dockerfile
# ---- Stage 1: build the SPA -------------------------------------------------
FROM node:22-alpine AS web
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# ---- Stage 2: runtime -------------------------------------------------------
FROM python:3.13-slim
WORKDIR /app

RUN pip install --no-cache-dir uv

# Editable/source install is REQUIRED: spa_dist_dir() in api/app.py resolves
# the repo root from __file__ (src/ layout), so the package must run from /app.
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv pip install --system -e .

# Runtime assets. config/ ships as read-only DEFAULTS; the entrypoint seeds
# the volume from it on first boot and symlinks /app/config -> /app/data/config.
COPY templates ./templates
COPY resume-template ./resume-template
COPY config ./config.defaults
COPY --from=web /build/web/dist ./web/dist
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV BROWSER_ENABLED=false
EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
```

Note: if `templates/` or `resume-template/` are absent or renamed, check what `render/` and cover-letter code read at runtime (`rg "templates/" src/`) and copy those paths instead.

- [ ] **Step 3: Write `railway.json`**

```json
{
  "$schema": "https://railway.com/railway.schema.json",
  "build": {
    "builder": "DOCKERFILE",
    "dockerfilePath": "Dockerfile"
  },
  "deploy": {
    "healthcheckPath": "/api/health",
    "healthcheckTimeout": 120,
    "restartPolicyType": "ON_FAILURE",
    "restartPolicyMaxRetries": 3
  }
}
```

- [ ] **Step 4: Write `docs/deploy-railway.md`**

```markdown
# Deploying to Railway

Spec: `docs/superpowers/specs/2026-07-10-railway-deploy-design.md` · ADR 0002.
Single-tenant: one account, one service, one volume.

## One-time setup

1. **Create the service**: Railway dashboard → New Project → Deploy from GitHub
   repo → pick this repo, branch `main`. `railway.json` supplies the Dockerfile
   build and the `/api/health` healthcheck.
2. **Attach the volume**: service → Settings → Volumes → mount path `/app/data`.
   (One volume per service; this pins the service to 1 replica — by design.)
3. **Set Platform secrets** (service → Variables). Generate the hash locally
   with `resume-agent hash-password`; generate the session secret with
   `python -c "import secrets; print(secrets.token_hex(32))"`:

   | Variable | Value |
   | --- | --- |
   | `AUTH_USERNAME` | your login name |
   | `AUTH_PASSWORD_HASH` | output of `resume-agent hash-password` |
   | `SESSION_SECRET` | 64 hex chars; rotating it logs out every session |
   | `API_TOKEN` | (optional) bearer for curl/CLI scripts |
   | `BROWSER_ENABLED` | `false` (already the image default) |

   Operational secrets (LLM keys, GitHub, Adzuna, LinkedIn) are NOT set here —
   enter them in the web UI under Settings → Keys after first login. They live
   on the volume's `.env`. Setting one as a Railway variable would silently
   shadow the web editor — don't.
4. **Deploy**: push to `main` (or dashboard → Deploy). Wait for the healthcheck.
5. **Log in** at `https://<app>.up.railway.app`, then enter your LLM keys under
   Settings → Keys.

## Seeding from your local checkout

```bash
.venv/Scripts/python.exe scripts/pack_data.py --out seed.tar.gz
curl -H "Authorization: Bearer $API_TOKEN" -F "file=@seed.tar.gz" \
     "https://<app>.up.railway.app/api/admin/import?confirm=REPLACE"
```

Import full-replaces the data root and refuses while runs are active (409).

## Backups

```bash
curl -H "Authorization: Bearer $API_TOKEN" -o backup-$(date +%F).tar.gz \
     "https://<app>.up.railway.app/api/admin/export"
```

Run on any schedule you like. **The archive contains your API keys (`.env`)** —
store it like a secret. Restore = the import command above.

## Round-trip pull (Tesla / Adzuna enrichment / LinkedIn)

Browser connectors need a visible local browser and are disabled in cloud
(`BROWSER_ENABLED=false`); cloud pulls skip them with a per-URL reason. When
you want them:

1. Export (backup command above) and unpack over your local checkout:
   `tar -xzf backup-<date>.tar.gz -C data/` … extract `config/`, `output/`,
   `.env` members beside it (they sit at the archive root — see
   `scripts/pack_data.py` for the layout).
2. Run the local pull: `resume-agent pull` (local default is
   `BROWSER_ENABLED=true`).
3. Re-pack and import (seeding commands above).
4. **Do not mutate the cloud instance between steps 1 and 3** — the import
   clobbers everything since the export.

## What's degraded in cloud

- Tesla, LinkedIn, scrape recipes: skipped, recorded as per-URL failures.
- Adzuna: snippet-only (no browser enrichment).
- Everything HTTP (Greenhouse, Lever, Ashby, Workday, Google, SmartRecruiters,
  Workable, Recruitee, Personio, Breezy, JazzHR, BambooHR, RemoteOK, URL
  intake): unchanged.

## Session notes

- Cookie lifetime 30 days; rotate `SESSION_SECRET` to force logout everywhere.
- Changing `AUTH_PASSWORD_HASH` does not kill live sessions (rotate the secret
  too if you need that).
```

- [ ] **Step 5: Manual verification (requires Docker; skip gracefully if unavailable)**

```bash
docker build -t resume-agent .
docker run --rm -p 8000:8000 -v ra-data:/app/data \
  -e AUTH_USERNAME=owner \
  -e AUTH_PASSWORD_HASH="$(.venv/Scripts/python.exe -m resume_agent.cli hash-password --password test123)" \
  -e SESSION_SECRET=devsecret \
  resume-agent
```

Then verify from another shell:
- `curl -s http://localhost:8000/api/health` → `{"status":"ok"}`
- `curl -s http://localhost:8000/` → HTML containing the SPA shell (`<div id="root">`)
- `curl -s http://localhost:8000/api/pipeline` → 401 envelope
- Browser: `http://localhost:8000` redirects to the login page; logging in with `owner` / `test123` shows the dashboard. (Note: the Secure cookie works on `http://localhost` — browsers treat localhost as a secure context.)
- `docker exec` into the container: `ls -la /app` shows `config`, `output`, `.env` as symlinks into `/app/data`.

If Docker is not available locally, state that in the commit message; the Railway build itself is the fallback verification.

- [ ] **Step 6: Commit**

```bash
git add Dockerfile .dockerignore railway.json docs/deploy-railway.md
git commit -m "feat: Dockerfile, Railway config, deployment runbook"
```

---

## Post-plan checklist (operator actions, not code)

1. Push `main` to GitHub; connect the repo in Railway; attach the volume at `/app/data`; set the Platform secrets (runbook §One-time setup).
2. First deploy → log in → enter LLM keys in Settings → Keys.
3. Seed with `scripts/pack_data.py` + the import curl.
4. Add a calendar/cron reminder for the backup curl.
