# Gmail Multi-User Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewire the Gmail integration into the multi-user tenancy architecture (platform OAuth client + per-user override + per-user workspace tokens) and add three features: scheduled inbox sync, deterministic follow-up reminders, and an LLM email writer that produces Gmail drafts.

**Architecture:** Platform Google OAuth client in `Settings` with per-user override via the existing `secrets.env` overlay; per-user token files in workspaces; a signed-state web OAuth flow; an in-process asyncio scheduler in the FastAPI lifespan that enters each user's `UserContext`; reminders and email drafts ride the existing `Notification` table and a new `EmailDraft` table. Spec: `docs/superpowers/specs/2026-07-18-gmail-multi-user-design.md`.

**Tech Stack:** FastAPI, SQLModel/SQLite, google-auth / google-auth-oauthlib / google-api-python-client (already in `pyproject.toml`, always lazy-imported), agno via `llm_runner`, React + TanStack Query + openapi-typescript client.

## Global Constraints

- **Offline tests.** No live Google/LLM/network calls anywhere in the suite. Google SDK usage stays behind lazy imports inside functions.
- **Wire format is camelCase** via `CamelModel` (`api/schemas/base.py`); Python stays snake_case.
- **Contract drift gate:** any change to API schemas/routes requires `bash scripts/gen_ts_client.sh` and a passing `tests/api/test_openapi_contract.py`.
- **Never request or use `gmail.send`.** Scopes are exactly `gmail.readonly` + `gmail.compose`.
- **Scheduled/manual sync never auto-applies a status change** — proposals land as `Notification` rows only.
- **Error envelope:** all API errors go through `ApiException` (`api/errors.py`).
- Backend test command: `.venv/Scripts/python.exe -m pytest <paths> -q`. Lint: `.venv/Scripts/python.exe -m ruff check <paths>`. Web tests: `cd web && npx vitest run <paths>`.
- Commit after every task with a conventional-commit message.

---

### Task 1: Settings fields, workspace token path, secrets contract

**Files:**
- Modify: `src/resume_agent/config.py` (Settings class, after `advisor_model`)
- Modify: `src/resume_agent/tenancy/workspace.py` (WorkspacePaths)
- Modify: `src/resume_agent/api/schemas/secrets.py` (SECRET_FIELDS, SecretsUpdate)
- Test: `tests/test_gmail_credentials.py` (create)

**Interfaces:**
- Consumes: existing `Settings`, `WorkspacePaths`, `effective_settings` overlay.
- Produces: `Settings.google_oauth_client_id/google_oauth_client_secret: str`, `Settings.gmail_sync_interval_hours: int` (default 6, ge=0), `Settings.follow_up_days: int` (default 14, ge=0), `Settings.gmail_max_messages: int` (default 50, ge=1), `WorkspacePaths.gmail_token: Path`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gmail_credentials.py
from pathlib import Path

from resume_agent.api.schemas.secrets import SECRET_FIELDS
from resume_agent.config import Settings
from resume_agent.tenancy.workspace import (
    effective_settings,
    workspace_paths,
)


def test_settings_have_gmail_fields():
    s = Settings(_env_file=None)
    assert s.google_oauth_client_id == ""
    assert s.google_oauth_client_secret == ""
    assert s.gmail_sync_interval_hours == 6
    assert s.follow_up_days == 14
    assert s.gmail_max_messages == 50


def test_workspace_gmail_token_path(tmp_path: Path):
    paths = workspace_paths(tmp_path, "u1")
    assert paths.gmail_token == tmp_path / "users" / "u1" / "gmail_token.json"


def test_google_client_overlays_from_secrets_env(tmp_path: Path):
    paths = workspace_paths(tmp_path, "u1")
    paths.root.mkdir(parents=True)
    paths.secrets_env.write_text(
        "GOOGLE_OAUTH_CLIENT_ID=own-client\nGOOGLE_OAUTH_CLIENT_SECRET=own-secret\n",
        encoding="utf-8",
    )
    base = Settings(_env_file=None, google_oauth_client_id="platform-client")
    overlay = effective_settings(base, paths)
    assert overlay.settings.google_oauth_client_id == "own-client"
    assert overlay.settings.google_oauth_client_secret == "own-secret"


def test_secret_fields_include_google_client():
    assert SECRET_FIELDS["google_oauth_client_id"] == "GOOGLE_OAUTH_CLIENT_ID"
    assert SECRET_FIELDS["google_oauth_client_secret"] == "GOOGLE_OAUTH_CLIENT_SECRET"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gmail_credentials.py -q`
Expected: FAIL (AttributeError / KeyError — fields don't exist yet).

- [ ] **Step 3: Implement**

In `src/resume_agent/config.py`, add to `Settings` after `advisor_model: str = ""`:

```python
    # Gmail integration (platform OAuth client; users may override the client
    # via their workspace secrets.env — str fields join the overlay for free).
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    gmail_sync_interval_hours: int = Field(default=6, ge=0)  # 0 = scheduler off
    follow_up_days: int = Field(default=14, ge=0)  # 0 = reminders off
    gmail_max_messages: int = Field(default=50, ge=1)
```

In `src/resume_agent/tenancy/workspace.py`, add to `WorkspacePaths` after `secrets_env`:

```python
    @property
    def gmail_token(self) -> Path:
        return self.root / "gmail_token.json"
```

In `src/resume_agent/api/schemas/secrets.py`, add to `SECRET_FIELDS` (after `linkedin_password`):

```python
    "google_oauth_client_id": "GOOGLE_OAUTH_CLIENT_ID",
    "google_oauth_client_secret": "GOOGLE_OAUTH_CLIENT_SECRET",
```

and to `SecretsUpdate`:

```python
    google_oauth_client_id: str | None = None
    google_oauth_client_secret: str | None = None
```

- [ ] **Step 4: Run tests + regenerate contract**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gmail_credentials.py tests/api/test_secrets_router.py -q` → PASS
Run: `bash scripts/gen_ts_client.sh` (SecretsUpdate changed the OpenAPI schema)
Run: `.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add src/resume_agent/config.py src/resume_agent/tenancy/workspace.py src/resume_agent/api/schemas/secrets.py tests/test_gmail_credentials.py contracts/ web/src/lib/api/schema.ts
git commit -m "feat(gmail): settings, workspace token path, and secrets contract for multi-user Gmail"
```

---

### Task 2: Gmail error taxonomy + tenant-aware auth module

**Files:**
- Create: `src/resume_agent/gmail/errors.py`
- Create: `src/resume_agent/gmail/auth.py`
- Modify: `src/resume_agent/gmail/client.py` (delete `GMAIL_SCOPES`/`CREDENTIALS_PATH`/`TOKEN_PATH`/`build_gmail_service`; re-export the CLI builder)
- Test: `tests/test_gmail_auth.py` (create)

**Interfaces:**
- Consumes: `WorkspacePaths.gmail_token` (Task 1), `current_context()` from `tenancy/context.py`.
- Produces:
  - `gmail.errors.GmailError` (base, `code="GMAIL_ERROR"`), `GmailNotConnected` (`code="GMAIL_NOT_CONNECTED"`), `GmailScopeMissing` (`code="GMAIL_SCOPE_MISSING"`), `GmailApiError` (`code="GMAIL_API_ERROR"`).
  - `gmail.auth.SCOPE_READONLY: str`, `SCOPE_COMPOSE: str`, `GMAIL_SCOPES: list[str]`, `CREDENTIALS_PATH: str`.
  - `gmail.auth.token_path(data_dir: Path | None = None) -> Path`
  - `gmail.auth.save_token_json(raw: str, data_dir: Path | None = None) -> Path`
  - `gmail.auth.delete_token(data_dir: Path | None = None) -> bool`
  - `gmail.auth.load_credentials(data_dir: Path | None = None)` → `google.oauth2.credentials.Credentials | None`
  - `gmail.auth.granted_scopes(creds) -> list[str]`, `gmail.auth.has_compose(creds) -> bool`
  - `gmail.auth.build_service(data_dir: Path | None = None)` → Gmail service, raises `GmailNotConnected`
  - `gmail.auth.build_gmail_service_interactive(credentials_path: str = CREDENTIALS_PATH)` → CLI-only `InstalledAppFlow` fallback.
  - `gmail.client.build_gmail_service` stays importable (alias of `build_gmail_service_interactive`) so `cli.py` keeps working unchanged.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gmail_auth.py
import json
from pathlib import Path

import pytest

from resume_agent.config import Settings
from resume_agent.gmail import auth
from resume_agent.gmail.errors import GmailNotConnected
from resume_agent.tenancy.context import UserContext, use_context
from resume_agent.tenancy.workspace import workspace_paths


def _context(tmp_path: Path) -> UserContext:
    paths = workspace_paths(tmp_path, "u1")
    paths.root.mkdir(parents=True, exist_ok=True)
    return UserContext(
        user_id="u1",
        username="u1",
        role="member",
        paths=paths,
        settings=Settings(_env_file=None),
        engine=None,
        system_engine=None,
        own_key_providers=frozenset(),
    )


def _token_payload(scopes: list[str]) -> str:
    return json.dumps(
        {
            "token": "ya29.fake",
            "refresh_token": "refresh",
            "client_id": "cid",
            "client_secret": "csecret",
            "token_uri": "https://oauth2.googleapis.com/token",
            "scopes": scopes,
            "expiry": "2099-01-01T00:00:00Z",
        }
    )


def test_token_path_prefers_context_then_data_dir(tmp_path: Path):
    with use_context(_context(tmp_path)):
        assert auth.token_path() == tmp_path / "users" / "u1" / "gmail_token.json"
    assert auth.token_path(tmp_path) == tmp_path / "gmail_token.json"
    assert auth.token_path() == Path("data/gmail_token.json")


def test_load_credentials_absent_returns_none(tmp_path: Path):
    assert auth.load_credentials(tmp_path) is None


def test_load_and_scope_check_round_trip(tmp_path: Path):
    auth.save_token_json(_token_payload(auth.GMAIL_SCOPES), tmp_path)
    creds = auth.load_credentials(tmp_path)
    assert creds is not None
    assert auth.has_compose(creds)

    auth.save_token_json(_token_payload([auth.SCOPE_READONLY]), tmp_path)
    creds = auth.load_credentials(tmp_path)
    assert creds is not None
    assert not auth.has_compose(creds)


def test_delete_token(tmp_path: Path):
    auth.save_token_json(_token_payload(auth.GMAIL_SCOPES), tmp_path)
    assert auth.delete_token(tmp_path) is True
    assert auth.delete_token(tmp_path) is False


def test_build_service_raises_when_disconnected(tmp_path: Path):
    with pytest.raises(GmailNotConnected):
        auth.build_service(tmp_path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gmail_auth.py -q`
Expected: FAIL with `ModuleNotFoundError: resume_agent.gmail.auth`.

- [ ] **Step 3: Implement**

```python
# src/resume_agent/gmail/errors.py
"""Typed Gmail failure family. `.code` feeds run error_code and ApiException."""


class GmailError(Exception):
    code = "GMAIL_ERROR"


class GmailNotConnected(GmailError):
    """No token, or the stored token can no longer be refreshed."""

    code = "GMAIL_NOT_CONNECTED"


class GmailScopeMissing(GmailError):
    """Token lacks gmail.compose — reconnect to enable drafts."""

    code = "GMAIL_SCOPE_MISSING"


class GmailApiError(GmailError):
    """Quota/5xx/transport failure from the Gmail API."""

    code = "GMAIL_API_ERROR"
```

```python
# src/resume_agent/gmail/auth.py
"""Tenant-aware Gmail credential storage + service construction.

Tokens are per-user workspace files (never DB rows). The interactive
InstalledAppFlow survives for the local CLI only; the web flow lives in
api/routers/gmail.py. Google SDK imports stay lazy so the offline test
suite never needs them on the import path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from resume_agent.gmail.errors import GmailNotConnected
from resume_agent.tenancy.context import current_context

SCOPE_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
SCOPE_COMPOSE = "https://www.googleapis.com/auth/gmail.compose"
GMAIL_SCOPES = [SCOPE_READONLY, SCOPE_COMPOSE]
CREDENTIALS_PATH = "config/gmail_credentials.json"
_LEGACY_TOKEN_PATH = Path("data/gmail_token.json")


def token_path(data_dir: Path | None = None) -> Path:
    """Active workspace token, else <data_dir>/gmail_token.json, else legacy."""
    context = current_context()
    if context is not None:
        return context.paths.gmail_token
    if data_dir is not None:
        return Path(data_dir) / "gmail_token.json"
    return _LEGACY_TOKEN_PATH


def save_token_json(raw: str, data_dir: Path | None = None) -> Path:
    path = token_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw, encoding="utf-8")
    return path


def delete_token(data_dir: Path | None = None) -> bool:
    path = token_path(data_dir)
    if not path.is_file():
        return False
    path.unlink()
    return True


def load_credentials(data_dir: Path | None = None) -> Any | None:
    """Token file -> Credentials; refresh+persist if expired; None if absent/revoked."""
    path = token_path(data_dir)
    if not path.is_file():
        return None
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    try:
        creds = Credentials.from_authorized_user_file(str(path))
    except ValueError:
        return None
    if creds.valid:
        return creds
    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except RefreshError:
            return None
        path.write_text(creds.to_json(), encoding="utf-8")
        return creds
    return None


def granted_scopes(creds: Any) -> list[str]:
    return list(creds.scopes or [])


def has_compose(creds: Any) -> bool:
    return SCOPE_COMPOSE in granted_scopes(creds)


def build_service(data_dir: Path | None = None) -> Any:
    """Authenticated Gmail service for the active tenant, or GmailNotConnected."""
    creds = load_credentials(data_dir)
    if creds is None:
        raise GmailNotConnected("Gmail is not connected for this workspace")
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=creds)


def build_gmail_service_interactive(credentials_path: str = CREDENTIALS_PATH) -> Any:
    """CLI-only: reuse a stored token, else run the local-browser consent flow."""
    creds = load_credentials()
    if creds is None:
        from google_auth_oauthlib.flow import InstalledAppFlow

        flow = InstalledAppFlow.from_client_secrets_file(credentials_path, GMAIL_SCOPES)
        creds = flow.run_local_server(port=0)
        save_token_json(creds.to_json())
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=creds)
```

In `src/resume_agent/gmail/client.py`: delete the `GMAIL_SCOPES`, `CREDENTIALS_PATH`, `TOKEN_PATH` constants and the whole `build_gmail_service` function (and the now-unused `Path` import if nothing else uses it), then add near the top:

```python
from resume_agent.gmail.auth import build_gmail_service_interactive as build_gmail_service  # noqa: F401  — CLI compat
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gmail_auth.py tests/test_cli_sync_status.py tests/test_gmail_classify.py tests/test_gmail_match.py tests/test_gmail_propose.py -q`
Expected: PASS (CLI test mocks `build_gmail_service`, which still resolves).

- [ ] **Step 5: Lint + commit**

```bash
.venv/Scripts/python.exe -m ruff check src/resume_agent/gmail tests/test_gmail_auth.py
git add src/resume_agent/gmail tests/test_gmail_auth.py
git commit -m "feat(gmail): tenant-aware auth module + typed error taxonomy"
```

---

### Task 3: OAuth web flow endpoints (connect / callback / status / disconnect)

**Files:**
- Create: `src/resume_agent/api/schemas/gmail.py`
- Create: `src/resume_agent/api/routers/gmail.py`
- Modify: `src/resume_agent/api/app.py` (register routers; init `app.state.gmail_oauth_states = {}` right after `app.state.login_limiter = FailedAttemptLimiter()`)
- Test: `tests/api/test_gmail_router.py` (create)

**Interfaces:**
- Consumes: `issue_link_token`/`verify_link_token` (`api/auth.py`, purpose `"gmail-oauth"`), `gmail.auth` (Task 2), `get_data_dir`/`get_settings_dep` (`api/deps.py`), `build_context` + `use_context` (tenancy).
- Produces:
  - `GET /api/gmail/connect` → `GmailConnectOut {authUrl: str}` (guarded)
  - `GET /api/gmail/callback?code=&state=` → 302 redirect to `/settings/keys?gmail=<connected|denied|invalid|error>` (unguarded, `include_in_schema=False`)
  - `GET /api/gmail/status` → `GmailStatusOut {connected: bool, scopes: list[str], draftCapable: bool, clientSource: str}` (guarded)
  - `DELETE /api/gmail/token` → `GmailStatusOut` (guarded)
  - Router-internal seam `_build_flow(settings, redirect_uri)` — the only place `google_auth_oauthlib.flow.Flow` is constructed; tests monkeypatch it.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_gmail_router.py
import json
from types import SimpleNamespace

from resume_agent.gmail import auth as gmail_auth


class _FakeFlow:
    """Stands in for google_auth_oauthlib Flow in both connect and callback."""

    def __init__(self):
        self.fetched_code = None

    def authorization_url(self, **kwargs):
        return (f"https://accounts.google.com/o/oauth2/auth?state={kwargs['state']}", kwargs["state"])

    def fetch_token(self, code: str):
        self.fetched_code = code

    @property
    def credentials(self):
        return SimpleNamespace(
            to_json=lambda: json.dumps(
                {
                    "token": "t",
                    "refresh_token": "r",
                    "client_id": "cid",
                    "client_secret": "cs",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "scopes": gmail_auth.GMAIL_SCOPES,
                    "expiry": "2099-01-01T00:00:00Z",
                }
            )
        )


def _patch_flow(monkeypatch):
    from resume_agent.api.routers import gmail as gmail_router

    flow = _FakeFlow()
    monkeypatch.setattr(gmail_router, "_build_flow", lambda settings, redirect_uri: flow)
    return flow


def test_connect_requires_client(client):
    response = client.get("/api/gmail/connect")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "GMAIL_CLIENT_MISSING"


def test_connect_callback_status_disconnect_cycle(client, monkeypatch):
    _patch_flow(monkeypatch)
    app = client.app
    app.state.settings = app.state.settings.model_copy(
        update={"google_oauth_client_id": "cid", "google_oauth_client_secret": "cs"}
    )

    connected = client.get("/api/gmail/connect")
    assert connected.status_code == 200
    auth_url = connected.json()["authUrl"]
    state = auth_url.split("state=", 1)[1]

    callback = client.get(
        f"/api/gmail/callback?code=abc&state={state}", follow_redirects=False
    )
    assert callback.status_code == 307
    assert "gmail=connected" in callback.headers["location"]

    status = client.get("/api/gmail/status")
    assert status.status_code == 200
    body = status.json()
    assert body["connected"] is True
    assert body["draftCapable"] is True

    gone = client.delete("/api/gmail/token")
    assert gone.status_code == 200
    assert gone.json()["connected"] is False


def test_callback_rejects_forged_state(client, monkeypatch):
    _patch_flow(monkeypatch)
    response = client.get(
        "/api/gmail/callback?code=abc&state=forged", follow_redirects=False
    )
    assert response.status_code == 307
    assert "gmail=invalid" in response.headers["location"]


def test_callback_denied_by_user(client):
    response = client.get(
        "/api/gmail/callback?error=access_denied&state=x", follow_redirects=False
    )
    assert response.status_code == 307
    assert "gmail=denied" in response.headers["location"]
```

Note: use the standard `client` fixture from `tests/api/conftest.py` (in-memory app, no system engine → the router's local-mode state store is exercised; token lands under the app's `data_dir`). If the conftest client's `data_dir` is not a tmp path, pass/override it the same way neighboring router tests do — read `tests/api/conftest.py` first and reuse its pattern.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_gmail_router.py -q`
Expected: FAIL (404s — routes don't exist).

- [ ] **Step 3: Implement schemas + router**

```python
# src/resume_agent/api/schemas/gmail.py
from __future__ import annotations

from resume_agent.api.schemas.base import CamelModel


class GmailConnectOut(CamelModel):
    auth_url: str


class GmailStatusOut(CamelModel):
    connected: bool
    scopes: list[str] = []
    draft_capable: bool = False
    client_source: str = "platform"  # "platform" | "own"
```

```python
# src/resume_agent/api/routers/gmail.py
"""Gmail account connection: OAuth web flow + status + disconnect.

The callback is unguarded — Google's top-level redirect may not carry
SameSite cookies — and authenticates via the signed `state` instead
(link token, purpose "gmail-oauth"). In no-tenancy local mode a random
in-memory state (app.state.gmail_oauth_states) replaces the signature.
"""

from __future__ import annotations

import secrets as pysecrets
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from resume_agent.api import auth as auth_module
from resume_agent.api.deps import get_data_dir
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.gmail import GmailConnectOut, GmailStatusOut
from resume_agent.config import Settings, get_settings
from resume_agent.gmail import auth as gmail_auth
from resume_agent.tenancy.context import current_context, use_context

router = APIRouter()
callback_router = APIRouter()

_STATE_TTL_SECONDS = 600
_SETTINGS_PAGE = "/settings/keys"


def _build_flow(settings: Settings, redirect_uri: str) -> Any:
    from google_auth_oauthlib.flow import Flow

    client_config = {
        "web": {
            "client_id": settings.google_oauth_client_id,
            "client_secret": settings.google_oauth_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    return Flow.from_client_config(
        client_config, scopes=gmail_auth.GMAIL_SCOPES, redirect_uri=redirect_uri
    )


def _redirect_uri(request: Request) -> str:
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.url.netloc
    return f"{proto}://{host}/api/gmail/callback"


def _require_client(settings: Settings) -> None:
    if not (settings.google_oauth_client_id and settings.google_oauth_client_secret):
        raise ApiException(
            409,
            "GMAIL_CLIENT_MISSING",
            "No Google OAuth client configured. Set GOOGLE_OAUTH_CLIENT_ID and "
            "GOOGLE_OAUTH_CLIENT_SECRET (platform) or add your own in Settings.",
        )


def _issue_state(request: Request) -> str:
    context = current_context()
    if context is not None:
        return auth_module.issue_link_token(
            request.app.state.settings, user_id=context.user_id, purpose="gmail-oauth"
        )
    state = pysecrets.token_urlsafe(24)
    request.app.state.gmail_oauth_states[state] = time.time() + _STATE_TTL_SECONDS
    return state


@router.get("/gmail/connect", response_model=GmailConnectOut)
def gmail_connect(request: Request):
    settings = get_settings()
    _require_client(settings)
    flow = _build_flow(settings, _redirect_uri(request))
    url, _state = flow.authorization_url(
        access_type="offline", prompt="consent", state=_issue_state(request)
    )
    return GmailConnectOut(auth_url=url)


def _finish(outcome: str) -> RedirectResponse:
    return RedirectResponse(f"{_SETTINGS_PAGE}?gmail={outcome}")


def _resolve_callback_user(request: Request, state: str):
    """Return (user, valid). user is None in valid local mode."""
    system_engine = getattr(request.app.state, "system_engine", None)
    if system_engine is None:
        expiry = request.app.state.gmail_oauth_states.pop(state, None)
        return None, expiry is not None and expiry >= time.time()
    user_id = auth_module.verify_link_token(
        state, request.app.state.settings, purpose="gmail-oauth"
    )
    if user_id is None:
        return None, False
    from sqlalchemy.orm import Session as SystemSession

    from resume_agent.tenancy.system_db import User

    with SystemSession(system_engine, expire_on_commit=False) as session:
        user = session.get(User, user_id)
        if user is not None:
            session.expunge(user)
    return user, user is not None and user.disabled_at is None


@callback_router.get("/gmail/callback", include_in_schema=False)
def gmail_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error:
        return _finish("denied")
    user, valid = _resolve_callback_user(request, state)
    if not valid:
        return _finish("invalid")
    try:
        if user is None:
            settings = request.app.state.settings
            _require_client(settings)
            flow = _build_flow(settings, _redirect_uri(request))
            flow.fetch_token(code=code)
            gmail_auth.save_token_json(
                flow.credentials.to_json(), request.app.state.data_dir
            )
        else:
            from resume_agent.tenancy.bootstrap import build_context

            context = build_context(
                user,
                request.app.state.data_dir,
                request.app.state.settings,
                request.app.state.engine_registry,
                system_engine=request.app.state.system_engine,
                template_dir=request.app.state.template_config_dir,
            )
            with use_context(context):
                settings = get_settings()  # effective: user client override wins
                _require_client(settings)
                flow = _build_flow(settings, _redirect_uri(request))
                flow.fetch_token(code=code)
                gmail_auth.save_token_json(flow.credentials.to_json())
    except ApiException:
        return _finish("error")
    except Exception:  # noqa: BLE001 — never render a raw OAuth error page
        return _finish("error")
    return _finish("connected")


def _status(request: Request) -> GmailStatusOut:
    creds = gmail_auth.load_credentials(get_data_dir(request))
    context = current_context()
    base_client = request.app.state.settings.google_oauth_client_id
    effective_client = get_settings().google_oauth_client_id
    client_source = (
        "own"
        if context is not None and effective_client and effective_client != base_client
        else "platform"
    )
    if creds is None:
        return GmailStatusOut(connected=False, client_source=client_source)
    return GmailStatusOut(
        connected=True,
        scopes=gmail_auth.granted_scopes(creds),
        draft_capable=gmail_auth.has_compose(creds),
        client_source=client_source,
    )


@router.get("/gmail/status", response_model=GmailStatusOut)
def gmail_status(request: Request):
    return _status(request)


@router.delete("/gmail/token", response_model=GmailStatusOut)
def gmail_disconnect(request: Request):
    data_dir = get_data_dir(request)
    creds = gmail_auth.load_credentials(data_dir)
    if creds is not None and creds.token:
        try:
            import httpx

            httpx.post(
                "https://oauth2.googleapis.com/revoke",
                params={"token": creds.token},
                timeout=10,
            )
        except Exception:  # noqa: BLE001 — revoke is best-effort
            pass
    gmail_auth.delete_token(data_dir)
    return _status(request)
```

In `src/resume_agent/api/app.py`:
- add `from resume_agent.api.routers import gmail as gmail_router` to the router imports;
- add `app.state.gmail_oauth_states = {}` right after the `app.state.login_limiter = FailedAttemptLimiter()` line;
- register (next to the notifications router registration):

```python
    app.include_router(gmail_router.router, prefix="/api", dependencies=guarded)
    app.include_router(gmail_router.callback_router, prefix="/api")
```

- [ ] **Step 4: Run tests + regenerate contract**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_gmail_router.py -q` → PASS
Run: `bash scripts/gen_ts_client.sh` then `.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -q` → PASS

- [ ] **Step 5: Lint + commit**

```bash
.venv/Scripts/python.exe -m ruff check src/resume_agent/api tests/api/test_gmail_router.py
git add src/resume_agent/api tests/api/test_gmail_router.py contracts/ web/src/lib/api/schema.ts
git commit -m "feat(gmail): OAuth web flow — connect, signed-state callback, status, disconnect"
```

---

### Task 4: Body-aware classification + wired cheap-tier LLM fallback

**Files:**
- Modify: `src/resume_agent/gmail/client.py` (EmailMessage.body, body extraction)
- Modify: `src/resume_agent/gmail/classify.py` (body in rules text, `build_classifier_llm`, `hydrating_classifier`)
- Test: `tests/test_gmail_body.py` (create), extend `tests/test_gmail_classify.py`

**Interfaces:**
- Consumes: `html_to_text` from `resume_agent.discovery.connectors.text`, `model_for_tier` from `resume_agent.tailor.agents`, `AgentRunner`, `build_model`, `resolve_api_key`, `retry_kwargs` from `llm_runner`.
- Produces:
  - `EmailMessage.body: str | None = None` (new dataclass field, default keeps all callers working)
  - `gmail.client.extract_body(payload: dict) -> str` (text/plain preferred, else html→text, truncated to `BODY_CHAR_LIMIT = 4000`)
  - `gmail.client.fetch_message_body(service, message_id: str) -> str`
  - `gmail.classify.build_classifier_llm() -> Runner | None` (None when no key for the cheap tier)
  - `gmail.classify.hydrating_classifier(service, llm: Runner | None) -> Callable[[EmailMessage], str]` — fetches the body on first classify of a message, then delegates to `classify_email`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_gmail_body.py
import base64

from resume_agent.gmail.classify import hydrating_classifier
from resume_agent.gmail.client import EmailMessage, extract_body, fetch_message_body


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def _payload_plain(text: str) -> dict:
    return {"mimeType": "text/plain", "body": {"data": _b64(text)}}


def test_extract_body_prefers_text_plain_in_multipart():
    payload = {
        "mimeType": "multipart/alternative",
        "body": {},
        "parts": [
            {"mimeType": "text/html", "body": {"data": _b64("<p>HTML version</p>")}},
            _payload_plain("plain version"),
        ],
    }
    assert extract_body(payload) == "plain version"


def test_extract_body_falls_back_to_html():
    payload = {"mimeType": "text/html", "body": {"data": _b64("<p>Hello <b>there</b></p>")}}
    assert "Hello" in extract_body(payload)
    assert "<p>" not in extract_body(payload)


def test_extract_body_truncates():
    payload = _payload_plain("x" * 10_000)
    assert len(extract_body(payload)) <= 4000


class _FakeMessages:
    def __init__(self, payload):
        self._payload = payload

    def get(self, userId, id, format):
        payload = self._payload
        return type("Req", (), {"execute": staticmethod(lambda: {"payload": payload})})()


class _FakeService:
    def __init__(self, payload):
        self._messages = _FakeMessages(payload)

    def users(self):
        messages = self._messages
        return type("Users", (), {"messages": staticmethod(lambda: messages)})()


def test_fetch_message_body_via_service():
    service = _FakeService(_payload_plain("Unfortunately we will not proceed."))
    assert "Unfortunately" in fetch_message_body(service, "m1")


def test_hydrating_classifier_uses_body_rules():
    service = _FakeService(_payload_plain("Unfortunately we chose other candidates."))
    classify = hydrating_classifier(service, llm=None)
    email = EmailMessage(
        sender="hr@acme.com",
        sender_domain="acme.com",
        subject="Your application",
        snippet="Update on your application",
        message_id="m1",
    )
    assert classify(email) == "rejection"
    assert email.body is not None  # hydrated in place, fetched once
```

Also add to `tests/test_gmail_classify.py`:

```python
def test_classify_prefers_body_over_snippet():
    from resume_agent.gmail.client import EmailMessage
    from resume_agent.gmail.classify import classify_email

    email = EmailMessage(
        sender="hr@acme.com",
        sender_domain="acme.com",
        subject="Update",
        snippet="no keywords here",
        body="We are pleased to offer you the position.",
    )
    assert classify_email(email) == "offer"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gmail_body.py tests/test_gmail_classify.py -q`
Expected: FAIL (no `extract_body`, no `body` field).

- [ ] **Step 3: Implement**

In `src/resume_agent/gmail/client.py`, add `body: str | None = None` as the last `EmailMessage` field, and append:

```python
import base64

from resume_agent.discovery.connectors.text import html_to_text

BODY_CHAR_LIMIT = 4000


def _decode(data: str) -> str:
    try:
        return base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors="replace")
    except (ValueError, TypeError):
        return ""


def _walk_parts(payload: dict):
    yield payload
    for part in payload.get("parts") or []:
        yield from _walk_parts(part)


def extract_body(payload: dict) -> str:
    """text/plain part preferred, else html→text; truncated for classification."""
    html = ""
    for part in _walk_parts(payload):
        data = (part.get("body") or {}).get("data") or ""
        if not data:
            continue
        if part.get("mimeType") == "text/plain":
            return _decode(data)[:BODY_CHAR_LIMIT].strip()
        if part.get("mimeType") == "text/html" and not html:
            html = _decode(data)
    return html_to_text(html)[:BODY_CHAR_LIMIT].strip() if html else ""


def fetch_message_body(service, message_id: str) -> str:
    msg = service.users().messages().get(userId="me", id=message_id, format="full").execute()
    return extract_body(msg.get("payload", {}))
```

(If `html_to_text` in `discovery/connectors/text.py` has a different exact name/signature, check it first and adapt the call — it exists and is the JD HTML→text helper.)

In `src/resume_agent/gmail/classify.py`, change the rules text line in `classify_email` to include the body:

```python
    text = f"{email.subject}\n{email.body or email.snippet}".lower()
```

change `_prompt` to use the same content:

```python
def _prompt(email: EmailMessage) -> str:
    return (
        "Classify this recruiting email as exactly one word: "
        "rejection, interview, assessment, offer, or none.\n\n"
        f"Subject: {email.subject}\nBody: {email.body or email.snippet}"
    )
```

and append:

```python
def build_classifier_llm() -> Runner | None:
    """Cheap-tier fallback agent, or None when that provider has no key."""
    from resume_agent.llm_runner import AgentRunner, build_model, resolve_api_key, retry_kwargs
    from resume_agent.tailor.agents import model_for_tier

    model_id = model_for_tier("cheap")
    if not resolve_api_key(model_id):
        return None
    from agno.agent import Agent

    return AgentRunner(Agent(model=build_model(model_id), **retry_kwargs()))


def hydrating_classifier(service, llm: Runner | None):
    """Classifier that lazily fetches the full body for matched messages.

    propose_transitions only calls classify AFTER an email matched an
    application, so the body fetch happens for matches only.
    """
    from resume_agent.gmail.client import fetch_message_body

    def classify(email: EmailMessage) -> str:
        if email.body is None and email.message_id:
            try:
                email.body = fetch_message_body(service, email.message_id)
            except Exception:  # noqa: BLE001 — snippet-only is a fine fallback
                email.body = ""
        return classify_email(email, llm)

    return classify
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gmail_body.py tests/test_gmail_classify.py tests/test_gmail_propose.py -q`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
.venv/Scripts/python.exe -m ruff check src/resume_agent/gmail tests/test_gmail_body.py tests/test_gmail_classify.py
git add src/resume_agent/gmail tests/test_gmail_body.py tests/test_gmail_classify.py
git commit -m "feat(gmail): body-aware classification with wired cheap-tier LLM fallback"
```

---

### Task 5: Follow-up reminders + kind-aware notifications API

**Files:**
- Create: `src/resume_agent/services/reminders.py`
- Modify: `src/resume_agent/services/notifications.py` (`accept_notification` branches on kind)
- Modify: `src/resume_agent/api/schemas/notifications.py` (job projection fields)
- Modify: `src/resume_agent/api/routers/notifications.py` (join job info)
- Test: `tests/test_services_reminders.py` (create)

**Interfaces:**
- Consumes: `application_job_pairs` (`tracking/queries.py`), `notification_by_key`, `save_notification` (`tracking/repository.py`), `Settings.follow_up_days` (Task 1).
- Produces:
  - `services.reminders.FOLLOW_UP_KIND = "follow_up"`
  - `services.reminders.create_follow_up_reminders(session, *, days: int | None = None, now: datetime | None = None) -> list[Notification]`
  - `NotificationOut` gains `job_id: int | None`, `company: str | None`, `title: str | None` (camelCase on the wire).
  - `accept_notification` on a `follow_up` row marks accepted WITHOUT touching application status.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_services_reminders.py
from datetime import datetime, timedelta, timezone

from sqlmodel import Session

from resume_agent.db import init_db, make_engine
from resume_agent.services.notifications import accept_notification, list_pending
from resume_agent.services.reminders import FOLLOW_UP_KIND, create_follow_up_reminders
from resume_agent.tracking.repository import get_application, save_application, save_job
from resume_agent.tracking.tables import Application, Job


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _seed(session: Session, *, status: str = "submitted", days_old: int = 20) -> Application:
    job = save_job(session, Job(source="manual", company="Acme", title="Eng"))
    assert job.id is not None
    app = save_application(session, Application(job_id=job.id, status=status))
    app.updated_at = _now() - timedelta(days=days_old)
    session.add(app)
    session.commit()
    return app


def test_stale_submitted_application_gets_one_reminder():
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        _seed(session, days_old=20)
        first = create_follow_up_reminders(session, days=14, now=_now())
        again = create_follow_up_reminders(session, days=14, now=_now())
        assert len(first) == 1
        assert first[0].kind == FOLLOW_UP_KIND
        assert first[0].proposed_status == ""
        assert again == []  # same episode → deduped


def test_fresh_and_terminal_applications_are_skipped():
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        _seed(session, days_old=3)
        _seed(session, status="rejected", days_old=40)
        assert create_follow_up_reminders(session, days=14, now=_now()) == []


def test_zero_days_disables_reminders():
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        _seed(session, days_old=100)
        assert create_follow_up_reminders(session, days=0, now=_now()) == []


def test_accept_follow_up_does_not_change_status():
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        app = _seed(session, days_old=20)
        assert app.id is not None
        [reminder] = create_follow_up_reminders(session, days=14, now=_now())
        assert reminder.id is not None
        accepted = accept_notification(session, reminder.id)
        assert accepted is not None and accepted.state == "accepted"
        refreshed = get_application(session, app.id)
        assert refreshed is not None and refreshed.status == "submitted"
        assert list_pending(session) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_reminders.py -q`
Expected: FAIL with `ModuleNotFoundError: resume_agent.services.reminders`.

- [ ] **Step 3: Implement**

```python
# src/resume_agent/services/reminders.py
"""Deterministic stale-application reminders. No LLM, no email parsing.

One reminder per staleness episode: the dedupe key embeds the
application's last-activity date, so a dismissal stays dismissed until
real activity bumps updated_at and a new episode begins.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlmodel import Session

from resume_agent.config import get_settings
from resume_agent.tracking.queries import application_job_pairs
from resume_agent.tracking.repository import notification_by_key, save_notification
from resume_agent.tracking.tables import Notification, utcnow

FOLLOW_UP_KIND = "follow_up"
_STALE_STATUSES = {"submitted", "interview"}


def follow_up_key(application_id: int, anchor: datetime) -> str:
    return f"followup:{application_id}:{anchor.date().isoformat()}"


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


def create_follow_up_reminders(
    session: Session,
    *,
    days: int | None = None,
    now: datetime | None = None,
) -> list[Notification]:
    days = get_settings().follow_up_days if days is None else days
    if days <= 0:
        return []
    now = _aware(now or utcnow())
    created: list[Notification] = []
    for app, job in application_job_pairs(session):
        if app.id is None or app.status not in _STALE_STATUSES:
            continue
        anchor = _aware(app.updated_at)
        if now - anchor < timedelta(days=days):
            continue
        key = follow_up_key(app.id, anchor)
        if notification_by_key(session, app.id, key) is not None:
            continue
        created.append(
            save_notification(
                session,
                Notification(
                    application_id=app.id,
                    kind=FOLLOW_UP_KIND,
                    proposed_status="",
                    evidence=(
                        f"No activity for {(now - anchor).days} days — "
                        f"{job.company} · {job.title}"
                    ),
                    message_id=key,
                ),
            )
        )
    return created
```

In `src/resume_agent/services/notifications.py`, replace the body of `accept_notification` with:

```python
def accept_notification(session: Session, notification_id: int) -> Notification | None:
    notification = get_notification(session, notification_id)
    if notification is None:
        return None
    # Reminder kinds carry no status proposal — accepting only acknowledges.
    if notification.proposed_status:
        update_application_status(
            session, notification.application_id, notification.proposed_status
        )
    notification.state = "accepted"
    return save_notification(session, notification)
```

In `src/resume_agent/api/schemas/notifications.py`, add to `NotificationOut`:

```python
    job_id: int | None = None
    company: str | None = None
    title: str | None = None
```

In `src/resume_agent/api/routers/notifications.py`, add a projection helper and use it in all three handlers (replace each `NotificationOut.model_validate(...)` call):

```python
from resume_agent.tracking.tables import Application, Job


def _to_out(session: Session, notification) -> NotificationOut:
    out = NotificationOut.model_validate(notification)
    application = session.get(Application, notification.application_id)
    if application is not None:
        job = session.get(Job, application.job_id)
        if job is not None:
            return out.model_copy(
                update={"job_id": job.id, "company": job.company, "title": job.title}
            )
    return out
```

- [ ] **Step 4: Run tests + regenerate contract**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_reminders.py tests/test_services_notifications.py -q` → PASS
Run: `bash scripts/gen_ts_client.sh` then `.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -q` → PASS

- [ ] **Step 5: Lint + commit**

```bash
.venv/Scripts/python.exe -m ruff check src/resume_agent/services src/resume_agent/api tests/test_services_reminders.py
git add src/resume_agent/services src/resume_agent/api tests/test_services_reminders.py contracts/ web/src/lib/api/schema.ts
git commit -m "feat(gmail): deterministic follow-up reminders riding the notification table"
```

---

### Task 6: Shared sync work unit + rewired manual sync endpoint

**Files:**
- Create: `src/resume_agent/services/gmail_sync.py`
- Modify: `src/resume_agent/api/routers/runs.py` (`launch_gmail_sync`)
- Test: `tests/test_services_gmail_sync.py` (create)

**Interfaces:**
- Consumes: `gmail.auth.build_service`/`load_credentials` (Task 2), `hydrating_classifier`/`build_classifier_llm` (Task 4), `sync_notifications` (services), `create_follow_up_reminders` (Task 5), `Settings.gmail_max_messages` (Task 1).
- Produces: `services.gmail_sync.run_gmail_sync(engine, reporter, *, service=None, llm=None) -> dict` — the single sync work unit used by the manual endpoint (this task) and the scheduler (Task 7). `service`/`llm` params exist for tests and default to real construction.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_services_gmail_sync.py
from datetime import datetime, timedelta, timezone

import pytest
from sqlmodel import Session

from resume_agent.db import init_db, make_engine
from resume_agent.gmail.errors import GmailNotConnected
from resume_agent.progress import ProgressReporter
from resume_agent.services.gmail_sync import run_gmail_sync
from resume_agent.tracking.repository import save_application, save_job
from resume_agent.tracking.tables import Application, Job


class _FakeListing:
    def __init__(self, messages):
        self._messages = messages

    def list(self, **kwargs):
        refs = [{"id": m["id"]} for m in self._messages]
        return type("Req", (), {"execute": staticmethod(lambda: {"messages": refs})})()

    def get(self, userId, id, format, metadataHeaders=None):
        msg = next(m for m in self._messages if m["id"] == id)
        if format == "full":
            result = {"payload": msg.get("payload", {})}
        else:
            result = {
                "payload": {"headers": msg["headers"]},
                "snippet": msg.get("snippet", ""),
                "threadId": msg.get("threadId"),
            }
        return type("Req", (), {"execute": staticmethod(lambda: result)})()


class FakeGmailService:
    def __init__(self, messages):
        self._messages = _FakeListing(messages)

    def users(self):
        messages = self._messages
        return type("Users", (), {"messages": staticmethod(lambda: messages)})()


def _reporter(tmp_path):
    return ProgressReporter("test-run", root=tmp_path)


def test_run_gmail_sync_creates_notifications_and_reminders(tmp_path):
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        job = save_job(session, Job(source="manual", company="Acme", title="Eng"))
        assert job.id is not None
        app = save_application(session, Application(job_id=job.id, status="submitted"))
        app.updated_at = datetime.now(timezone.utc) - timedelta(days=30)
        session.add(app)
        session.commit()

    service = FakeGmailService(
        [
            {
                "id": "m1",
                "headers": [
                    {"name": "From", "value": "hr@acme.com"},
                    {"name": "Subject", "value": "Interview at Acme"},
                ],
                "snippet": "Schedule a call",
                "threadId": "t1",
            }
        ]
    )
    result = run_gmail_sync(engine, _reporter(tmp_path), service=service, llm=None)
    assert result["pending"] >= 1
    assert result["reminders"] == 1


def test_run_gmail_sync_disconnected_raises(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # isolate from a real legacy data/gmail_token.json
    engine = make_engine("sqlite://")
    init_db(engine)
    with pytest.raises(GmailNotConnected):
        run_gmail_sync(engine, _reporter(tmp_path))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_gmail_sync.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# src/resume_agent/services/gmail_sync.py
"""One sync pass: fetch inbox → propose status changes → follow-up reminders.

Shared by the manual POST /api/gmail/sync run and the scheduler tick, so
the two can never drift. Never auto-applies a status change.
"""

from __future__ import annotations

from typing import Any

from resume_agent.config import get_settings
from resume_agent.db import get_session
from resume_agent.gmail.auth import build_service
from resume_agent.gmail.classify import build_classifier_llm, hydrating_classifier
from resume_agent.gmail.client import fetch_recent_messages
from resume_agent.llm_runner import Runner
from resume_agent.services.notifications import sync_notifications
from resume_agent.services.reminders import create_follow_up_reminders


def run_gmail_sync(
    engine: Any,
    reporter: Any,
    *,
    service: Any | None = None,
    llm: Runner | None = None,
) -> dict:
    reporter.begin(2, "Scanning Gmail")
    if service is None:
        service = build_service()
    if llm is None:
        llm = build_classifier_llm()
    emails = fetch_recent_messages(
        service, max_results=get_settings().gmail_max_messages
    )
    classify = hydrating_classifier(service, llm)
    with get_session(engine) as session:
        pending = sync_notifications(session, emails, classify=classify)
        reporter.step(1, label="Checking follow-ups")
        reminders = create_follow_up_reminders(session)
    reporter.step(2, label="Done")
    return {"pending": len(pending), "reminders": len(reminders)}
```

Note: `llm=None` passed to `hydrating_classifier` means rules-only — `test_run_gmail_sync_creates_notifications_and_reminders` passes `llm=None` explicitly, but `run_gmail_sync`'s default calls `build_classifier_llm()` which returns None offline (no key). To keep the test deterministic regardless of local env keys, the test passes `llm=None` — that works because the fake message hits the "interview" rule. ALSO: to make the explicit `llm=None` distinguishable from "build one", use a sentinel:

```python
_UNSET = object()


def run_gmail_sync(engine, reporter, *, service=None, llm: Any = _UNSET) -> dict:
    ...
    if llm is _UNSET:
        llm = build_classifier_llm()
```

Use the sentinel version.

In `src/resume_agent/api/routers/runs.py`, replace the body of `launch_gmail_sync`:

```python
@router.post("/gmail/sync", response_model=RunOut, status_code=202)
def launch_gmail_sync(request: Request, mgr: RunManager = Depends(get_run_manager)):
    from resume_agent.gmail.auth import load_credentials

    engine = _engine(request)
    if load_credentials() is None:
        raise ApiException(
            409, "GMAIL_NOT_CONNECTED", "Connect Gmail in Settings before syncing"
        )

    def work(reporter):
        from resume_agent.services.gmail_sync import run_gmail_sync

        return run_gmail_sync(engine, reporter)

    run_id = _submit(mgr, "gmailSync", work, singleton_key="gmailSync")
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(record)
```

(`load_credentials()` with no args resolves the active tenant workspace via `current_context()`; the no-tenancy in-memory test app has no token file → 409, which existing launch tests for gmail sync may rely on — check `tests/api/test_runs_launch.py` for a gmailSync case and update its expectation to 409 + `GMAIL_NOT_CONNECTED` if it asserted 202 before.)

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_services_gmail_sync.py tests/api/test_runs_launch.py -q`
Expected: PASS (after updating any stale gmailSync launch expectation as noted).

- [ ] **Step 5: Lint + commit**

```bash
.venv/Scripts/python.exe -m ruff check src/resume_agent/services/gmail_sync.py src/resume_agent/api/routers/runs.py tests/test_services_gmail_sync.py
git add src/resume_agent/services/gmail_sync.py src/resume_agent/api/routers/runs.py tests/test_services_gmail_sync.py tests/api/test_runs_launch.py
git commit -m "feat(gmail): shared sync work unit; manual sync pre-checks connection"
```

---

### Task 7: In-process scheduler

**Files:**
- Create: `src/resume_agent/gmail/scheduler.py`
- Modify: `src/resume_agent/api/app.py` (lifespan start/stop)
- Test: `tests/test_gmail_scheduler.py` (create)

**Interfaces:**
- Consumes: `run_gmail_sync` (Task 6), `RunManager.submit`, `build_context` (`tenancy/bootstrap.py`), `workspace_paths`, `use_context`, `ACTIVE_RUN_STATES` (`api/runs/models.py`), `token_path` (Task 2).
- Produces:
  - `gmail.scheduler.tick(state, *, work=run_gmail_sync) -> dict[str, str]` — one async pass over all connected users; `state` is any object exposing `system_engine`, `engine_registry`, `settings`, `template_config_dir`, `data_dir`, `run_manager`, `engine` (the FastAPI `app.state` in production, a `SimpleNamespace` in tests). Returns `{owner: run_id | "error: ..."}`; `"local"` is the owner key in no-tenancy mode.
  - `gmail.scheduler.scheduler_loop(state) -> None` — sleeps `settings.gmail_sync_interval_hours` between ticks, forever; started/cancelled by the lifespan.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gmail_scheduler.py
import asyncio
from concurrent.futures import Executor, Future
from pathlib import Path
from types import SimpleNamespace

from resume_agent.api.runs.manager import RunManager
from resume_agent.db import init_db, make_engine
from resume_agent.gmail.scheduler import tick


class InlineExecutor(Executor):
    def submit(self, fn, *args, **kwargs):
        future: Future = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as exc:  # noqa: BLE001
            future.set_exception(exc)
        return future


def _state(tmp_path: Path) -> SimpleNamespace:
    engine = make_engine("sqlite://")
    init_db(engine)
    return SimpleNamespace(
        system_engine=None,
        engine_registry=None,
        settings=None,
        template_config_dir=Path("config"),
        data_dir=tmp_path,
        run_manager=RunManager(root=tmp_path / "runs", executor=InlineExecutor()),
        engine=engine,
    )


def test_tick_skips_when_no_token(tmp_path):
    state = _state(tmp_path)
    result = asyncio.run(tick(state, work=lambda engine, reporter: {"pending": 0}))
    assert result == {}


def test_tick_runs_local_sync_when_token_exists(tmp_path):
    state = _state(tmp_path)
    (tmp_path / "gmail_token.json").write_text("{}", encoding="utf-8")
    calls = []

    def fake_work(engine, reporter, **kwargs):
        reporter.begin(1, "fake")
        calls.append(engine)
        reporter.step(1)
        return {"pending": 0, "reminders": 0}

    result = asyncio.run(tick(state, work=fake_work))
    assert "local" in result
    snapshot = state.run_manager.get(result["local"])
    assert snapshot is not None and snapshot.state.value == "done"
    assert calls == [state.engine]


def test_tick_isolates_a_failing_user(tmp_path):
    state = _state(tmp_path)
    (tmp_path / "gmail_token.json").write_text("{}", encoding="utf-8")

    def failing_work(engine, reporter, **kwargs):
        reporter.begin(1, "fake")
        raise RuntimeError("boom")

    result = asyncio.run(tick(state, work=failing_work))
    snapshot = state.run_manager.get(result["local"])
    assert snapshot is not None and snapshot.state.value == "error"
```

(Multi-user tick paths reuse `build_context`, which the tenancy suite already covers; the scheduler test exercises the no-tenancy branch plus failure isolation, which is the scheduler's own logic. If `tests/tenancy/` offers a ready-made fixture that builds a system engine with two users, add one multi-user tick test with token files in both workspaces — worth it, but do not build new tenancy fixtures from scratch here.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gmail_scheduler.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# src/resume_agent/gmail/scheduler.py
"""Background Gmail sync: one asyncio task, one serial pass per tick.

Each user's pass is isolated — a revoked token or quota error never
aborts the loop. Runs are submitted through the RunManager so scheduled
syncs appear on the Runs page and share the per-user gmailSync singleton
with the manual endpoint.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from sqlalchemy import select

from resume_agent.api.runs.models import ACTIVE_RUN_STATES
from resume_agent.gmail.auth import token_path
from resume_agent.services.gmail_sync import run_gmail_sync
from resume_agent.tenancy.context import use_context
from resume_agent.tenancy.workspace import workspace_paths

logger = logging.getLogger(__name__)

_POLL_SECONDS = 1.0
_MAX_WAIT_SECONDS = 900


async def _wait_terminal(run_manager: Any, run_id: str) -> None:
    for _ in range(int(_MAX_WAIT_SECONDS / _POLL_SECONDS)):
        snapshot = run_manager.get(run_id)
        if snapshot is None or snapshot.state not in ACTIVE_RUN_STATES:
            return
        await asyncio.sleep(_POLL_SECONDS)


def _submit(state: Any, engine: Any, work: Callable[..., dict], user_id: str | None) -> str:
    def run(reporter):
        return work(engine, reporter)

    return state.run_manager.submit(
        "gmailSync",
        run,
        singleton_key="gmailSync",
        user_id=user_id,
        meta={"scheduled": True},
    )


async def tick(state: Any, *, work: Callable[..., dict] = run_gmail_sync) -> dict[str, str]:
    """One serial pass over every connected owner. Never raises per-user errors."""
    results: dict[str, str] = {}
    if state.system_engine is None:
        if token_path(state.data_dir).is_file():
            try:
                run_id = _submit(state, state.engine, work, user_id=None)
                results["local"] = run_id
                await _wait_terminal(state.run_manager, run_id)
            except Exception as exc:  # noqa: BLE001 — isolate; next tick retries
                logger.warning("scheduled gmail sync failed: %s", exc)
                results["local"] = f"error: {exc}"
        return results

    from sqlalchemy.orm import Session as SystemSession

    from resume_agent.tenancy.bootstrap import build_context
    from resume_agent.tenancy.system_db import User

    with SystemSession(state.system_engine, expire_on_commit=False) as session:
        users = list(
            session.execute(select(User).where(User.disabled_at.is_(None)))
            .scalars()
            .all()
        )
        for user in users:
            session.expunge(user)
    for user in users:
        paths = workspace_paths(state.data_dir, user.id)
        if not paths.gmail_token.is_file():
            continue
        try:
            context = build_context(
                user,
                state.data_dir,
                state.settings,
                state.engine_registry,
                system_engine=state.system_engine,
                template_dir=state.template_config_dir,
            )
            state.run_manager.register_root(context.paths.runs_root)
            with use_context(context):
                run_id = _submit(state, context.engine, work, user_id=user.id)
            results[user.id] = run_id
            await _wait_terminal(state.run_manager, run_id)
        except Exception as exc:  # noqa: BLE001 — one user never aborts the loop
            logger.warning("scheduled gmail sync failed for %s: %s", user.id, exc)
            results[user.id] = f"error: {exc}"
    return results


async def scheduler_loop(state: Any) -> None:
    interval_hours = state.settings.gmail_sync_interval_hours
    while True:
        await asyncio.sleep(interval_hours * 3600)
        try:
            await tick(state)
        except Exception:  # noqa: BLE001 — the loop must survive anything
            logger.exception("gmail scheduler tick crashed")
```

(Verify the `User` primary-key/disabled attributes against `src/resume_agent/tenancy/system_db.py` — `deps.py` uses `session.get(User, user_id)` and `user.disabled_at`, so `User.id` and `User.disabled_at` are the expected names; adjust if the model differs.)

In `src/resume_agent/api/app.py` lifespan, after `app.state.run_manager.sweep()` add:

```python
        app.state.gmail_scheduler_task = None
        if (
            not _is_memory_db(resolved_db)
            and resolved_settings.gmail_sync_interval_hours > 0
        ):
            from resume_agent.gmail.scheduler import scheduler_loop

            app.state.gmail_scheduler_task = asyncio.create_task(
                scheduler_loop(app.state)
            )
        yield
        if app.state.gmail_scheduler_task is not None:
            app.state.gmail_scheduler_task.cancel()
            with suppress(asyncio.CancelledError):
                await app.state.gmail_scheduler_task
```

(replacing the bare `yield`; add `import asyncio` and `from contextlib import suppress` to the module imports).

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_gmail_scheduler.py tests/api/test_app_health.py -q`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
.venv/Scripts/python.exe -m ruff check src/resume_agent/gmail/scheduler.py src/resume_agent/api/app.py tests/test_gmail_scheduler.py
git add src/resume_agent/gmail/scheduler.py src/resume_agent/api/app.py tests/test_gmail_scheduler.py
git commit -m "feat(gmail): in-process scheduler with per-user isolation and runs telemetry"
```

---

### Task 8: EmailDraft table, repository helpers, delete cascade

**Files:**
- Modify: `src/resume_agent/tracking/tables.py` (new model after `Notification`)
- Modify: `src/resume_agent/tracking/repository.py` (CRUD + cascade)
- Test: `tests/test_email_draft_repository.py` (create)

**Interfaces:**
- Consumes: existing SQLModel table conventions (`utcnow`, `cast(Any, ...)` tablename).
- Produces:
  - `tracking.tables.EmailDraft` — fields: `id: int | None` (pk), `job_id: int` (FK jobs.id, indexed), `draft_type: str`, `subject: str`, `body: str`, `to_addr: str = ""`, `gmail_thread_id: str | None`, `gmail_draft_id: str | None`, `state: str = "generated"` (`generated|saved`), `created_at: datetime`.
  - `repository.save_email_draft(session, draft) -> EmailDraft`, `repository.get_email_draft(session, draft_id) -> EmailDraft | None`, `repository.email_drafts_for_job(session, job_id) -> list[EmailDraft]` (newest first).
  - `delete_job_row` cascades `EmailDraft`; `has_progress` is UNCHANGED (drafts never gate deletion).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_email_draft_repository.py
from sqlmodel import Session

from resume_agent.db import init_db, make_engine
from resume_agent.tracking.repository import (
    delete_job_row,
    email_drafts_for_job,
    get_email_draft,
    has_progress,
    save_email_draft,
    save_job,
)
from resume_agent.tracking.tables import EmailDraft, Job


def _draft(job_id: int, subject: str = "Following up") -> EmailDraft:
    return EmailDraft(
        job_id=job_id, draft_type="follow_up", subject=subject, body="Hi —"
    )


def test_save_and_list_newest_first():
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        job = save_job(session, Job(source="manual", company="Acme", title="Eng"))
        assert job.id is not None
        first = save_email_draft(session, _draft(job.id, "one"))
        second = save_email_draft(session, _draft(job.id, "two"))
        drafts = email_drafts_for_job(session, job.id)
        assert [d.subject for d in drafts] == ["two", "one"]
        assert first.id is not None
        assert get_email_draft(session, first.id) is not None
        assert second.state == "generated"


def test_drafts_never_gate_deletion_and_cascade():
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        job = save_job(session, Job(source="manual", company="Acme", title="Eng"))
        assert job.id is not None
        save_email_draft(session, _draft(job.id))
        assert has_progress(session, job.id) is False  # invariant: no gate
        delete_job_row(session, job)
        assert email_drafts_for_job(session, job.id) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_email_draft_repository.py -q`
Expected: FAIL with ImportError (`EmailDraft`).

- [ ] **Step 3: Implement**

In `src/resume_agent/tracking/tables.py`, after the `Notification` class:

```python
class EmailDraft(SQLModel, table=True):
    __tablename__ = cast(Any, "email_drafts")

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="jobs.id", index=True)
    draft_type: str  # follow_up | thank_you | withdrawal | cold_outreach
    subject: str
    body: str
    to_addr: str = ""
    gmail_thread_id: str | None = None
    gmail_draft_id: str | None = None
    state: str = Field(default="generated")  # generated | saved
    created_at: datetime = Field(default_factory=utcnow)
```

In `src/resume_agent/tracking/repository.py`: import `EmailDraft` in the tables import block, change the `delete_job_row` cascade tuple to `(CoverLetter, Application, ResumeVersion, EmailDraft)`, and add:

```python
def save_email_draft(session: Session, draft: EmailDraft) -> EmailDraft:
    session.add(draft)
    session.commit()
    session.refresh(draft)
    return draft


def get_email_draft(session: Session, draft_id: int) -> EmailDraft | None:
    return session.get(EmailDraft, draft_id)


def email_drafts_for_job(session: Session, job_id: int) -> list[EmailDraft]:
    id_col = cast(Any, EmailDraft.id)
    return list(
        session.exec(
            select(EmailDraft)
            .where(EmailDraft.job_id == job_id)
            .order_by(id_col.desc())
        ).all()
    )
```

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_email_draft_repository.py tests/test_applications_repository.py -q`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
.venv/Scripts/python.exe -m ruff check src/resume_agent/tracking tests/test_email_draft_repository.py
git add src/resume_agent/tracking tests/test_email_draft_repository.py
git commit -m "feat(gmail): EmailDraft table with FK-safe cascade, no progress gating"
```

---

### Task 9: Email writer service

**Files:**
- Create: `src/resume_agent/services/email_writer.py`
- Test: `tests/test_email_writer.py` (create)

**Interfaces:**
- Consumes: `EmailDraft` + repository (Task 8), `fetch_recent_messages`/`fetch_message_body` (Task 4), `match_email_to_application` (`gmail/match.py`), `AgentRunner`/`build_model`/`retry_kwargs`/`use_json_mode_for` (`llm_runner`), `model_for_tier` (`tailor/agents.py`), `ExtensibleModel` (`models/base.py`).
- Produces:
  - `DRAFT_TYPES = ("follow_up", "thank_you", "withdrawal", "cold_outreach")`
  - `EmailDraftContent(ExtensibleModel)` with `subject: str`, `body: str`
  - `build_writer_agent() -> Runner`
  - `generate_email_draft(session, job_id: int, draft_type: str, instructions: str | None = None, *, facts_path: str = "data/profile/facts.json", agent: Runner | None = None, service: Any | None = None) -> EmailDraft` — raises `ValueError` on unknown type or missing job; `service=None` means no thread context (cold path).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_email_writer.py
import json
from types import SimpleNamespace

import pytest
from sqlmodel import Session

from resume_agent.db import init_db, make_engine
from resume_agent.services.email_writer import (
    DRAFT_TYPES,
    EmailDraftContent,
    generate_email_draft,
)
from resume_agent.tracking.repository import save_application, save_job
from resume_agent.tracking.tables import Application, Job


class _FakeAgent:
    def __init__(self):
        self.prompts: list[str] = []

    def run(self, prompt: str):
        self.prompts.append(prompt)
        return SimpleNamespace(
            content=EmailDraftContent(subject="Following up on Eng", body="Hi — ...")
        )

    async def arun(self, prompt: str):  # Runner protocol
        return self.run(prompt)


def _facts(tmp_path) -> str:
    path = tmp_path / "facts.json"
    path.write_text(json.dumps({"summary": "Engineer with Python."}), encoding="utf-8")
    return str(path)


def test_generate_persists_draft_without_thread(tmp_path):
    engine = make_engine("sqlite://")
    init_db(engine)
    agent = _FakeAgent()
    with Session(engine) as session:
        job = save_job(session, Job(source="manual", company="Acme", title="Eng"))
        assert job.id is not None
        save_application(session, Application(job_id=job.id, status="submitted"))
        draft = generate_email_draft(
            session, job.id, "follow_up",
            facts_path=_facts(tmp_path), agent=agent, service=None,
        )
    assert draft.id is not None
    assert draft.subject == "Following up on Eng"
    assert draft.to_addr == ""  # no thread context → user fills recipient
    assert draft.state == "generated"
    prompt = agent.prompts[0]
    assert "Acme" in prompt and "Engineer with Python." in prompt


def test_generate_rejects_unknown_type(tmp_path):
    engine = make_engine("sqlite://")
    init_db(engine)
    with Session(engine) as session:
        job = save_job(session, Job(source="manual", company="Acme", title="Eng"))
        assert job.id is not None
        with pytest.raises(ValueError):
            generate_email_draft(
                session, job.id, "spam", facts_path=_facts(tmp_path), agent=_FakeAgent()
            )


def test_draft_types_frozen():
    assert DRAFT_TYPES == ("follow_up", "thank_you", "withdrawal", "cold_outreach")
```

Add a thread-context test using the `FakeGmailService` shape from `tests/test_services_gmail_sync.py` (copy the fake classes into this file — tasks may run out of order):

```python
def test_generate_uses_matched_thread(tmp_path):
    # FakeGmailService copied from tests/test_services_gmail_sync.py
    from tests.test_services_gmail_sync import FakeGmailService

    engine = make_engine("sqlite://")
    init_db(engine)
    agent = _FakeAgent()
    service = FakeGmailService(
        [
            {
                "id": "m1",
                "headers": [
                    {"name": "From", "value": "Jane Doe <jane@acme.com>"},
                    {"name": "Subject", "value": "Interview at Acme"},
                ],
                "snippet": "Schedule a call",
                "threadId": "t1",
            }
        ]
    )
    with Session(engine) as session:
        job = save_job(session, Job(source="manual", company="Acme", title="Eng"))
        assert job.id is not None
        draft = generate_email_draft(
            session, job.id, "follow_up",
            facts_path=_facts(tmp_path), agent=agent, service=service,
        )
    assert draft.to_addr == "jane@acme.com"
    assert draft.gmail_thread_id == "t1"
```

(If importing from another test module is awkward under the repo's pytest config, inline the fake service classes instead — they are ~25 lines.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_email_writer.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# src/resume_agent/services/email_writer.py
"""LLM email drafting grounded in profile facts. Human gate, never sends.

The prompt's only permitted source for claims about the user is
facts.json — same evidence discipline as tailoring, but the hard gate is
the human editing the draft in Gmail, not an LLM reviewer round.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from sqlmodel import Session

from resume_agent.config import get_settings
from resume_agent.gmail.client import fetch_message_body, fetch_recent_messages
from resume_agent.gmail.match import match_email_to_application
from resume_agent.llm_runner import Runner
from resume_agent.models.base import ExtensibleModel
from resume_agent.tracking.repository import (
    application_for_job,
    get_job,
    save_email_draft,
)
from resume_agent.tracking.tables import EmailDraft

DRAFT_TYPES = ("follow_up", "thank_you", "withdrawal", "cold_outreach")

_TYPE_GUIDANCE = {
    "follow_up": "A short, warm check-in on the application's status. 80-140 words.",
    "thank_you": "A brief thank-you after an interview, referencing the role. 60-120 words.",
    "withdrawal": "A gracious withdrawal of the application. 50-100 words.",
    "cold_outreach": "A concise introduction expressing interest in the role. 100-160 words.",
}

_JD_CHAR_LIMIT = 2000
_FACTS_CHAR_LIMIT = 6000
_THREAD_CHAR_LIMIT = 1500

_WRITER_INSTRUCTIONS = (
    "You draft professional job-search emails. Claims about the candidate "
    "must come ONLY from the provided profile facts — never invent "
    "experience, numbers, or credentials. Match the requested tone and "
    "length. Return the subject and body."
)


class EmailDraftContent(ExtensibleModel):
    subject: str
    body: str


def build_writer_agent() -> Runner:
    from agno.agent import Agent

    from resume_agent.llm_runner import (
        AgentRunner,
        build_model,
        retry_kwargs,
        use_json_mode_for,
    )
    from resume_agent.tailor.agents import model_for_tier

    model = build_model(model_for_tier("mid"))
    return AgentRunner(
        Agent(
            model=model,
            description="Draft one professional job-search email.",
            instructions=_WRITER_INSTRUCTIONS,
            output_schema=EmailDraftContent,
            use_json_mode=use_json_mode_for(model),
            **retry_kwargs(),
        )
    )


_ADDR_RE = re.compile(r"<([^>]+)>")


def _sender_address(sender: str) -> str:
    match = _ADDR_RE.search(sender)
    if match:
        return match.group(1).strip()
    return sender.strip() if "@" in sender else ""


def _thread_context(service: Any, job) -> tuple[str, str, str] | None:
    """(sender_addr, thread_id, excerpt) from the newest matched inbox message."""
    emails = fetch_recent_messages(
        service, max_results=get_settings().gmail_max_messages
    )
    for email in emails:
        if match_email_to_application(email, [job]) is None:
            continue
        body = ""
        if email.message_id:
            try:
                body = fetch_message_body(service, email.message_id)
            except Exception:  # noqa: BLE001 — snippet is enough context
                body = ""
        excerpt = f"{email.subject}\n{body or email.snippet}"[:_THREAD_CHAR_LIMIT]
        return _sender_address(email.sender), email.thread_id or "", excerpt
    return None


def _load_facts(facts_path: str) -> str:
    path = Path(facts_path)
    if not path.is_file():
        return "{}"
    return json.dumps(json.loads(path.read_text(encoding="utf-8")))[:_FACTS_CHAR_LIMIT]


def _prompt(job, application, draft_type, instructions, facts, thread) -> str:
    lines = [
        f"Email type: {draft_type} — {_TYPE_GUIDANCE[draft_type]}",
        f"Company: {job.company}",
        f"Role: {job.title}",
        f"Application status: {application.status if application else 'not applied yet'}",
        f"Job description excerpt:\n{(job.jd_text or '')[:_JD_CHAR_LIMIT]}",
        f"Candidate profile facts (the ONLY permitted source for claims):\n{facts}",
    ]
    if thread is not None:
        lines.append(
            "This email replies to an existing thread. Latest message from "
            f"{thread[0]}:\n{thread[2]}"
        )
    if instructions:
        lines.append(f"Additional instructions from the candidate: {instructions}")
    return "\n\n".join(lines)


def generate_email_draft(
    session: Session,
    job_id: int,
    draft_type: str,
    instructions: str | None = None,
    *,
    facts_path: str = "data/profile/facts.json",
    agent: Runner | None = None,
    service: Any | None = None,
) -> EmailDraft:
    if draft_type not in DRAFT_TYPES:
        raise ValueError(f"Unknown draft type: {draft_type}")
    job = get_job(session, job_id)
    if job is None:
        raise ValueError(f"Job #{job_id} not found")
    application = application_for_job(session, job_id)
    thread = _thread_context(service, job) if service is not None else None
    agent = agent or build_writer_agent()
    response = agent.run(
        _prompt(job, application, draft_type, instructions, _load_facts(facts_path), thread)
    )
    content = response.content
    if not isinstance(content, EmailDraftContent):
        content = EmailDraftContent.model_validate_json(str(content))
    return save_email_draft(
        session,
        EmailDraft(
            job_id=job_id,
            draft_type=draft_type,
            subject=content.subject,
            body=content.body,
            to_addr=thread[0] if thread else "",
            gmail_thread_id=(thread[1] or None) if thread else None,
        ),
    )
```

(Verify `use_json_mode_for` and `ExtensibleModel` import paths against `profile/coach.py`'s imports — that module is the reference pattern for structured-output agents. Verify `Job.jd_text` is the JD field name in `tracking/tables.py`.)

- [ ] **Step 4: Run tests**

Run: `.venv/Scripts/python.exe -m pytest tests/test_email_writer.py -q`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
.venv/Scripts/python.exe -m ruff check src/resume_agent/services/email_writer.py tests/test_email_writer.py
git add src/resume_agent/services/email_writer.py tests/test_email_writer.py
git commit -m "feat(gmail): fact-grounded email writer service (drafts, human gate)"
```

---

### Task 10: Email draft API — generate run, list, save to Gmail

**Files:**
- Create: `src/resume_agent/api/schemas/email_drafts.py`
- Create: `src/resume_agent/api/routers/email_drafts.py`
- Modify: `src/resume_agent/api/app.py` (register router with `guarded`)
- Test: `tests/api/test_email_drafts.py` (create)

**Interfaces:**
- Consumes: `generate_email_draft`/`DRAFT_TYPES` (Task 9), `EmailDraft` repository (Task 8), `gmail.auth.build_service`/`load_credentials`/`has_compose` (Task 2), `GmailError` family, `RunManager` `_submit` pattern (`api/routers/runs.py`), `_workspace_args` for the facts path.
- Produces:
  - `POST /api/jobs/{job_id}/email-draft` body `EmailDraftRequest {draftType, instructions?}` → 202 `RunOut`, kind `"emailDraft"`, singleton `f"emailDraft:{job_id}"`; run result `{"draftId": id}`.
  - `GET /api/jobs/{job_id}/email-drafts` → `list[EmailDraftOut]` (newest first).
  - `POST /api/email-drafts/{draft_id}/save` → `EmailDraftOut` (creates/updates the Gmail draft; 409 `GMAIL_NOT_CONNECTED` / `GMAIL_SCOPE_MISSING`).
  - `EmailDraftOut`: `id, job_id, draft_type, subject, body, to_addr, gmail_thread_id?, gmail_draft_id?, state, created_at` (camelCase on the wire).

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_email_drafts.py
from types import SimpleNamespace


def _seed_job(client) -> int:
    # Reuse the job-creation pattern from tests/api/test_job_mutations.py —
    # read that file first and copy its seeding helper (direct DB insert via
    # the app engine is the established approach).
    from sqlmodel import Session

    from resume_agent.tracking.repository import save_job
    from resume_agent.tracking.tables import Job

    with Session(client.app.state.engine) as session:
        job = save_job(session, Job(source="manual", company="Acme", title="Eng"))
        assert job.id is not None
        return job.id


def test_generate_run_and_list(client, monkeypatch):
    from resume_agent.api.routers import email_drafts as router_module

    def fake_generate(session, job_id, draft_type, instructions=None, **kwargs):
        from resume_agent.services.email_writer import EmailDraftContent  # noqa: F401
        from resume_agent.tracking.repository import save_email_draft
        from resume_agent.tracking.tables import EmailDraft

        return save_email_draft(
            session,
            EmailDraft(job_id=job_id, draft_type=draft_type, subject="s", body="b"),
        )

    monkeypatch.setattr(router_module, "generate_email_draft", fake_generate)
    monkeypatch.setattr(router_module, "_service_or_none", lambda: None)
    job_id = _seed_job(client)

    launched = client.post(
        f"/api/jobs/{job_id}/email-draft", json={"draftType": "follow_up"}
    )
    assert launched.status_code == 202

    listed = client.get(f"/api/jobs/{job_id}/email-drafts")
    assert listed.status_code == 200
    [draft] = listed.json()
    assert draft["draftType"] == "follow_up"
    assert draft["state"] == "generated"


def test_generate_rejects_unknown_type(client):
    job_id = _seed_job(client)
    response = client.post(
        f"/api/jobs/{job_id}/email-draft", json={"draftType": "spam"}
    )
    assert response.status_code == 400


def test_save_requires_connection(client):
    from sqlmodel import Session

    from resume_agent.tracking.repository import save_email_draft
    from resume_agent.tracking.tables import EmailDraft

    job_id = _seed_job(client)
    with Session(client.app.state.engine) as session:
        draft = save_email_draft(
            session,
            EmailDraft(job_id=job_id, draft_type="follow_up", subject="s", body="b"),
        )
        draft_id = draft.id
    response = client.post(f"/api/email-drafts/{draft_id}/save")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "GMAIL_NOT_CONNECTED"


def test_save_creates_gmail_draft(client, monkeypatch):
    from resume_agent.api.routers import email_drafts as router_module
    from sqlmodel import Session

    from resume_agent.tracking.repository import save_email_draft
    from resume_agent.tracking.tables import EmailDraft

    created = {}

    class _Drafts:
        def create(self, userId, body):
            created["payload"] = body
            return SimpleNamespace(execute=lambda: {"id": "draft-123"})

        def update(self, userId, id, body):
            created["updated"] = id
            return SimpleNamespace(execute=lambda: {"id": id})

    class _Service:
        def users(self):
            drafts = _Drafts()
            return SimpleNamespace(drafts=lambda: drafts)

    monkeypatch.setattr(router_module, "_compose_service", lambda request: _Service())
    job_id = _seed_job(client)
    with Session(client.app.state.engine) as session:
        draft = save_email_draft(
            session,
            EmailDraft(
                job_id=job_id,
                draft_type="follow_up",
                subject="s",
                body="b",
                to_addr="jane@acme.com",
                gmail_thread_id="t1",
            ),
        )
        draft_id = draft.id

    response = client.post(f"/api/email-drafts/{draft_id}/save")
    assert response.status_code == 200
    body = response.json()
    assert body["gmailDraftId"] == "draft-123"
    assert body["state"] == "saved"
    assert created["payload"]["message"]["threadId"] == "t1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_email_drafts.py -q`
Expected: FAIL (404s).

- [ ] **Step 3: Implement**

```python
# src/resume_agent/api/schemas/email_drafts.py
from __future__ import annotations

from datetime import datetime

from resume_agent.api.schemas.base import CamelModel


class EmailDraftRequest(CamelModel):
    draft_type: str
    instructions: str | None = None


class EmailDraftOut(CamelModel):
    id: int
    job_id: int
    draft_type: str
    subject: str
    body: str
    to_addr: str
    gmail_thread_id: str | None = None
    gmail_draft_id: str | None = None
    state: str
    created_at: datetime
```

```python
# src/resume_agent/api/routers/email_drafts.py
"""Email writer endpoints: generate (202 run), list, save to Gmail drafts."""

from __future__ import annotations

import base64
from email.message import EmailMessage as MimeMessage
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from resume_agent.api.deps import get_run_manager, get_session
from resume_agent.api.errors import ApiException
from resume_agent.api.runs.manager import RunManager
from resume_agent.api.runs.sse import record_to_run
from resume_agent.api.schemas.email_drafts import EmailDraftOut, EmailDraftRequest
from resume_agent.api.schemas.runs import RunOut
from resume_agent.db import get_session as open_session
from resume_agent.gmail import auth as gmail_auth
from resume_agent.gmail.errors import GmailError, GmailNotConnected, GmailScopeMissing
from resume_agent.services.email_writer import DRAFT_TYPES, generate_email_draft
from resume_agent.tracking.repository import (
    email_drafts_for_job,
    get_email_draft,
    get_job,
    save_email_draft,
)

router = APIRouter()


def _service_or_none() -> Any | None:
    """Gmail service for thread context, or None when not connected."""
    try:
        return gmail_auth.build_service()
    except GmailNotConnected:
        return None


def _compose_service(request: Request) -> Any:
    """Draft-capable Gmail service, or a typed 409."""
    from resume_agent.api.deps import get_data_dir

    data_dir = get_data_dir(request)
    creds = gmail_auth.load_credentials(data_dir)
    if creds is None:
        raise GmailNotConnected("Connect Gmail in Settings to save drafts")
    if not gmail_auth.has_compose(creds):
        raise GmailScopeMissing("Reconnect Gmail to grant draft permission")
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=creds)


def _gmail_409(error: GmailError) -> ApiException:
    return ApiException(409, error.code, str(error))


@router.post("/jobs/{job_id}/email-draft", response_model=RunOut, status_code=202)
def launch_email_draft(
    job_id: int,
    body: EmailDraftRequest,
    request: Request,
    session: Session = Depends(get_session),
    mgr: RunManager = Depends(get_run_manager),
):
    if body.draft_type not in DRAFT_TYPES:
        raise ApiException(400, "INVALID_DRAFT_TYPE", f"Unknown type {body.draft_type}")
    if get_job(session, job_id) is None:
        raise ApiException(404, "NOT_FOUND", f"Job #{job_id} not found")
    from resume_agent.api.routers.runs import _engine, _submit, _workspace_args

    engine = _engine(request)
    facts_path = _workspace_args()["facts_path"]
    draft_type, instructions = body.draft_type, body.instructions

    def work(reporter):
        reporter.begin(1, "Drafting email")
        service = _service_or_none()
        with open_session(engine) as worker_session:
            draft = generate_email_draft(
                worker_session,
                job_id,
                draft_type,
                instructions,
                facts_path=facts_path,
                service=service,
            )
        reporter.step(1)
        return {"draftId": draft.id}

    run_id = _submit(
        mgr,
        "emailDraft",
        work,
        singleton_key=f"emailDraft:{job_id}",
        meta={"jobId": job_id},
    )
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(record)


@router.get("/jobs/{job_id}/email-drafts", response_model=list[EmailDraftOut])
def list_email_drafts(job_id: int, session: Session = Depends(get_session)):
    return [
        EmailDraftOut.model_validate(d) for d in email_drafts_for_job(session, job_id)
    ]


@router.post("/email-drafts/{draft_id}/save", response_model=EmailDraftOut)
def save_to_gmail(
    draft_id: int, request: Request, session: Session = Depends(get_session)
):
    draft = get_email_draft(session, draft_id)
    if draft is None:
        raise ApiException(404, "NOT_FOUND", f"Draft #{draft_id} not found")
    try:
        service = _compose_service(request)
        mime = MimeMessage()
        if draft.to_addr:
            mime["To"] = draft.to_addr
        mime["Subject"] = draft.subject
        mime.set_content(draft.body)
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
        message: dict[str, Any] = {"raw": raw}
        if draft.gmail_thread_id:
            message["threadId"] = draft.gmail_thread_id
        payload = {"message": message}
        drafts_api = service.users().drafts()
        if draft.gmail_draft_id:
            response = drafts_api.update(
                userId="me", id=draft.gmail_draft_id, body=payload
            ).execute()
        else:
            response = drafts_api.create(userId="me", body=payload).execute()
    except GmailError as error:
        raise _gmail_409(error) from error
    draft.gmail_draft_id = response.get("id")
    draft.state = "saved"
    return EmailDraftOut.model_validate(save_email_draft(session, draft))
```

In `src/resume_agent/api/app.py`: import `email_drafts as email_drafts_router` and register next to the notifications router:

```python
    app.include_router(email_drafts_router.router, prefix="/api", dependencies=guarded)
```

- [ ] **Step 4: Run tests + regenerate contract**

Run: `.venv/Scripts/python.exe -m pytest tests/api/test_email_drafts.py -q` → PASS
Run: `bash scripts/gen_ts_client.sh` then `.venv/Scripts/python.exe -m pytest tests/api/test_openapi_contract.py -q` → PASS

- [ ] **Step 5: Lint + commit**

```bash
.venv/Scripts/python.exe -m ruff check src/resume_agent/api tests/api/test_email_drafts.py
git add src/resume_agent/api tests/api/test_email_drafts.py contracts/ web/src/lib/api/schema.ts
git commit -m "feat(gmail): email draft endpoints — generate run, list, save to Gmail"
```

---

### Task 11: Web — Gmail connect card in Settings

**Files:**
- Create: `web/src/features/settings/use-gmail.ts`
- Create: `web/src/features/settings/GmailCard.tsx`
- Create: `web/src/features/settings/GmailCard.test.tsx`
- Modify: `web/src/features/settings/pages/KeysSettingsPage.tsx` (render `<GmailCard />`)

**Interfaces:**
- Consumes: `/api/gmail/status`, `/api/gmail/connect`, `DELETE /api/gmail/token` from the regenerated `web/src/lib/api/schema.ts`; `api`/`unwrap` from `@/lib/api/client`.
- Produces: `useGmailStatus()`, `useGmailConnect()`, `useGmailDisconnect()` hooks; `<GmailCard />` component.

- [ ] **Step 1: Write the hooks**

```ts
// web/src/features/settings/use-gmail.ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type GmailStatus = components["schemas"]["GmailStatusOut"];
const KEY = ["gmail-status"];

export function useGmailStatus() {
  return useQuery<GmailStatus>({
    queryKey: KEY,
    queryFn: () => unwrap(api.GET("/api/gmail/status")),
  });
}

export function useGmailConnect() {
  return useMutation({
    mutationFn: async () => {
      const out = await unwrap(api.GET("/api/gmail/connect"));
      window.location.href = out.authUrl;
    },
  });
}

export function useGmailDisconnect() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.DELETE("/api/gmail/token")),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  });
}
```

- [ ] **Step 2: Write the card + test**

```tsx
// web/src/features/settings/GmailCard.tsx
import { Mail } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useGmailConnect, useGmailDisconnect, useGmailStatus } from "./use-gmail";

export function GmailCard() {
  const { data: status, isLoading } = useGmailStatus();
  const connect = useGmailConnect();
  const disconnect = useGmailDisconnect();

  return (
    <section className="rounded-lg border p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="flex items-center gap-2 text-sm font-semibold">
            <Mail className="size-4" aria-hidden="true" /> Gmail
          </h3>
          <p className="mt-1 text-xs text-muted-foreground">
            {isLoading
              ? "Checking connection..."
              : status?.connected
                ? status.draftCapable
                  ? `Connected (${status.clientSource} client) — sync and drafts enabled.`
                  : `Connected (${status.clientSource} client) — reconnect to enable drafts.`
                : "Not connected. Connect to sync application status and draft emails."}
          </p>
        </div>
        {status?.connected ? (
          <div className="flex gap-2">
            {!status.draftCapable && (
              <Button size="sm" variant="outline" disabled={connect.isPending} onClick={() => connect.mutate()}>
                Reconnect
              </Button>
            )}
            <Button size="sm" variant="outline" disabled={disconnect.isPending} onClick={() => disconnect.mutate()}>
              Disconnect
            </Button>
          </div>
        ) : (
          <Button size="sm" disabled={connect.isPending || isLoading} onClick={() => connect.mutate()}>
            Connect Gmail
          </Button>
        )}
      </div>
    </section>
  );
}
```

Test — mock the hooks module (follow the established mocking style in `web/src/features/settings/use-config.test.tsx`; adapt render helpers to whatever that file uses):

```tsx
// web/src/features/settings/GmailCard.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { GmailCard } from "./GmailCard";

const mocks = vi.hoisted(() => ({
  status: { connected: false, scopes: [], draftCapable: false, clientSource: "platform" },
}));

vi.mock("./use-gmail", () => ({
  useGmailStatus: () => ({ data: mocks.status, isLoading: false }),
  useGmailConnect: () => ({ mutate: vi.fn(), isPending: false }),
  useGmailDisconnect: () => ({ mutate: vi.fn(), isPending: false }),
}));

describe("GmailCard", () => {
  it("offers connect when disconnected", () => {
    render(<GmailCard />);
    expect(screen.getByRole("button", { name: /connect gmail/i })).toBeInTheDocument();
  });

  it("offers reconnect when compose scope is missing", () => {
    mocks.status = { connected: true, scopes: ["readonly"], draftCapable: false, clientSource: "own" };
    render(<GmailCard />);
    expect(screen.getByRole("button", { name: /reconnect/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /disconnect/i })).toBeInTheDocument();
  });
});
```

In `web/src/features/settings/pages/KeysSettingsPage.tsx`: import `GmailCard` and render `<GmailCard />` after the existing secrets form section (read the file and place it at the end of the page's main column).

- [ ] **Step 3: Run web tests**

Run: `cd web && npx vitest run src/features/settings/GmailCard.test.tsx`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add web/src/features/settings
git commit -m "feat(web): Gmail connect card in Settings > Keys"
```

---

### Task 12: Web — kind-aware bell + email draft dialog

**Files:**
- Create: `web/src/features/job/use-email-drafts.ts`
- Create: `web/src/features/job/EmailDraftDialog.tsx`
- Modify: `web/src/features/notifications/NotificationsBell.tsx` (kind-aware rendering + Draft follow-up)
- Modify: `web/src/components/JobModal.tsx` ("Draft email" action opening the dialog)
- Test: `web/src/features/notifications/NotificationsBell.test.tsx` (create)

**Interfaces:**
- Consumes: `NotificationOut` now carrying `kind`/`jobId`/`company`/`title`; `/api/jobs/{job_id}/email-draft` + `/email-drafts` + `/api/email-drafts/{draft_id}/save` endpoints (Task 10); `watchRun` pattern from `use-notifications.ts`.
- Produces: `useEmailDrafts(jobId)`, `useGenerateEmailDraft(jobId)`, `useSaveEmailDraft(jobId)` hooks; `<EmailDraftDialog jobId defaultType open onOpenChange />`.

- [ ] **Step 1: Write the hooks**

```ts
// web/src/features/job/use-email-drafts.ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import { watchRun } from "@/lib/runs/sse";
import type { components } from "@/lib/api/schema";

export type EmailDraft = components["schemas"]["EmailDraftOut"];
type RunOut = components["schemas"]["RunOut"];

const key = (jobId: number) => ["email-drafts", jobId];

export function useEmailDrafts(jobId: number, enabled = true) {
  return useQuery<EmailDraft[]>({
    queryKey: key(jobId),
    enabled,
    queryFn: () =>
      unwrap(
        api.GET("/api/jobs/{job_id}/email-drafts", {
          params: { path: { job_id: jobId } },
        }),
      ),
  });
}

export function useGenerateEmailDraft(jobId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { draftType: string; instructions?: string }): Promise<RunOut> =>
      unwrap(
        api.POST("/api/jobs/{job_id}/email-draft", {
          params: { path: { job_id: jobId } },
          body,
        }),
      ),
    onSuccess: (run) => {
      watchRun(run.runId, "emailDraft", () =>
        qc.invalidateQueries({ queryKey: key(jobId) }),
      );
    },
  });
}

export function useSaveEmailDraft(jobId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (draftId: number) =>
      unwrap(
        api.POST("/api/email-drafts/{draft_id}/save", {
          params: { path: { draft_id: draftId } },
        }),
      ),
    onSuccess: () => qc.invalidateQueries({ queryKey: key(jobId) }),
  });
}
```

- [ ] **Step 2: Write the dialog**

```tsx
// web/src/features/job/EmailDraftDialog.tsx
import { useState } from "react";
import { Loader2, Mail, Save } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  useEmailDrafts,
  useGenerateEmailDraft,
  useSaveEmailDraft,
} from "./use-email-drafts";

const TYPES = [
  { value: "follow_up", label: "Follow-up" },
  { value: "thank_you", label: "Thank you" },
  { value: "withdrawal", label: "Withdrawal" },
  { value: "cold_outreach", label: "Cold outreach" },
] as const;

export function EmailDraftDialog({
  jobId,
  defaultType = "follow_up",
  open,
  onOpenChange,
}: {
  jobId: number;
  defaultType?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [draftType, setDraftType] = useState(defaultType);
  const [instructions, setInstructions] = useState("");
  const { data: drafts = [] } = useEmailDrafts(jobId, open);
  const generate = useGenerateEmailDraft(jobId);
  const save = useSaveEmailDraft(jobId);
  const latest = drafts[0];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Mail className="size-4" aria-hidden="true" /> Draft email
          </DialogTitle>
        </DialogHeader>
        <div className="flex flex-wrap gap-2">
          {TYPES.map((t) => (
            <Button
              key={t.value}
              size="sm"
              variant={draftType === t.value ? "default" : "outline"}
              onClick={() => setDraftType(t.value)}
            >
              {t.label}
            </Button>
          ))}
        </div>
        <textarea
          className="w-full rounded-md border bg-background p-2 text-sm"
          rows={2}
          placeholder="Optional instructions (e.g. mention the take-home score)"
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
        />
        <Button
          disabled={generate.isPending}
          onClick={() =>
            generate.mutate({ draftType, instructions: instructions || undefined })
          }
        >
          {generate.isPending && (
            <Loader2 className="size-4 animate-spin" aria-hidden="true" />
          )}
          Generate draft
        </Button>
        {latest && (
          <div className="space-y-2 rounded-lg border p-3 text-sm">
            <div className="text-xs text-muted-foreground">
              To: {latest.toAddr || "(fill in Gmail)"}
            </div>
            <div className="font-medium">{latest.subject}</div>
            <p className="whitespace-pre-wrap text-sm">{latest.body}</p>
            <div className="flex justify-end gap-2">
              <Button
                size="sm"
                variant="outline"
                onClick={() => navigator.clipboard.writeText(latest.body)}
              >
                Copy body
              </Button>
              <Button
                size="sm"
                disabled={save.isPending || latest.state === "saved"}
                onClick={() => latest.id && save.mutate(latest.id)}
              >
                <Save className="size-4" aria-hidden="true" />
                {latest.state === "saved" ? "Saved to Gmail" : "Save to Gmail drafts"}
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
```

(Check `web/src/components/ui/` for the dialog component's actual export names before using — if the repo's dialog primitive differs, follow the pattern used by an existing dialog such as the one in `JobModal.tsx` or `web/src/features/board`. A save failure with error code `GMAIL_SCOPE_MISSING`/`GMAIL_NOT_CONNECTED` should surface however `unwrap` errors are normally toasted in this app — follow the existing mutation-error pattern; the "Copy body" button is the always-available fallback.)

- [ ] **Step 3: Kind-aware bell**

In `web/src/features/notifications/NotificationsBell.tsx`:
- add local state `const [draftJobId, setDraftJobId] = useState<number | null>(null);` (import `useState` from react, `EmailDraftDialog` from `@/features/job/EmailDraftDialog`);
- replace the item body (`<div className="font-medium">Move to {item.proposedStatus}</div>`) with kind-aware copy:

```tsx
<div className="font-medium">
  {item.kind === "follow_up"
    ? `Follow up: ${item.company ?? "application"}`
    : `Move to ${item.proposedStatus}`}
</div>
```

- replace the Accept button with a kind-aware action:

```tsx
<Button
  size="sm"
  disabled={accept.isPending}
  onClick={() => {
    accept.mutate(item.id);
    if (item.kind === "follow_up" && item.jobId != null) {
      setDraftJobId(item.jobId);
    }
  }}
>
  <Check className="size-4" aria-hidden="true" />
  {item.kind === "follow_up" ? "Draft follow-up" : "Accept"}
</Button>
```

- render the dialog after the `</Popover>` close (wrap the component return in a fragment):

```tsx
{draftJobId != null && (
  <EmailDraftDialog
    jobId={draftJobId}
    defaultType="follow_up"
    open
    onOpenChange={(open) => !open && setDraftJobId(null)}
  />
)}
```

- update the popover subtitle from "Gmail-derived status proposals" to "Status proposals & follow-up reminders".

- [ ] **Step 4: Job modal entry point**

In `web/src/components/JobModal.tsx`: add `const [emailDraftOpen, setEmailDraftOpen] = useState(false);`, a "Draft email" `Button` (variant `outline`, `Mail` icon) in the modal's action row next to the existing stage/action buttons, and `<EmailDraftDialog jobId={job.id} open={emailDraftOpen} onOpenChange={setEmailDraftOpen} />` beside it. Read the file first and match its existing action-button layout and prop names (the job's id prop may be `job.id` or `jobId` — use what the file already has in scope).

- [ ] **Step 5: Write the bell test**

```tsx
// web/src/features/notifications/NotificationsBell.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { NotificationsBell } from "./NotificationsBell";

vi.mock("./use-notifications", () => ({
  useNotifications: () => ({
    data: [
      {
        id: 1,
        applicationId: 1,
        kind: "follow_up",
        proposedStatus: "",
        evidence: "No activity for 20 days — Acme · Eng",
        messageId: "followup:1:2026-06-28",
        state: "pending",
        createdAt: "2026-07-18T00:00:00Z",
        jobId: 7,
        company: "Acme",
        title: "Eng",
      },
    ],
    isLoading: false,
  }),
  useAcceptNotification: () => ({ mutate: vi.fn(), isPending: false }),
  useDismissNotification: () => ({ mutate: vi.fn(), isPending: false }),
  useGmailSync: () => ({ mutate: vi.fn(), isPending: false }),
}));

vi.mock("@/features/job/EmailDraftDialog", () => ({
  EmailDraftDialog: () => null,
}));

describe("NotificationsBell", () => {
  it("renders follow-up reminders with a draft action", async () => {
    render(<NotificationsBell />);
    // open the popover
    screen.getByRole("button", { name: /notifications/i }).click();
    expect(await screen.findByText(/follow up: acme/i)).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: /draft follow-up/i }),
    ).toBeInTheDocument();
  });
});
```

(If the popover needs a userEvent click instead of `.click()`, follow the interaction pattern in an existing popover test under `web/src/`.)

- [ ] **Step 6: Run web tests + typecheck**

Run: `cd web && npx vitest run src/features/notifications src/features/settings/GmailCard.test.tsx`
Expected: PASS.
Run: `cd web && npx tsc --noEmit` (or the repo's typecheck script if one exists in `package.json`)
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add web/src
git commit -m "feat(web): kind-aware notification bell + email draft dialog"
```

---

### Task 13: Full-suite verification + docs

**Files:**
- Modify: `CLAUDE.md` (add a Gmail design note)
- Modify: `.env.example` if present (document new env vars)

- [ ] **Step 1: Run the entire backend suite**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: PASS (0 failures).

- [ ] **Step 2: Run the entire web suite**

Run: `cd web && npx vitest run`
Expected: PASS.

- [ ] **Step 3: Lint everything touched**

Run: `.venv/Scripts/python.exe -m ruff check src tests`
Expected: clean.

- [ ] **Step 4: Add the CLAUDE.md design note**

Append to the "Known design notes" list in `CLAUDE.md`:

```markdown
- **Gmail is multi-user; drafts only, never send.** The platform OAuth client
  (`GOOGLE_OAUTH_CLIENT_ID/SECRET`) can be overridden per user via
  `secrets.env`; per-user tokens live at `{workspace}/gmail_token.json`
  (`gmail/auth.py` is the only credential seam; scopes = readonly + compose).
  The web callback authenticates via a signed link-token state, never the
  session cookie. An in-process scheduler (`gmail/scheduler.py`, every
  `gmail_sync_interval_hours`) runs `services/gmail_sync.run_gmail_sync`
  per connected user — sync proposals and deterministic stale-application
  reminders (`services/reminders.py`, episode-keyed dedupe in
  `Notification.message_id`) land in the notification bell; nothing
  auto-applies. `services/email_writer.py` grounds drafts in facts.json
  only (human gate, no LLM fact-check round) and saves them as in-thread
  Gmail drafts via `EmailDraft` rows; drafts never gate job deletion but
  cascade on delete. `gmail.send` is permanently out of scope.
```

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md .env.example
git commit -m "docs: Gmail multi-user integration design note"
```

---

## Self-Review Notes (already applied)

- **Spec coverage:** §1 credentials → Tasks 1–3; §2 scheduler+classification → Tasks 4, 6, 7; §3 reminders → Task 5; §4 writer → Tasks 8–10; §5 cross-cutting (errors Task 2, settings Task 1, tests throughout, CLAUDE.md Task 13); web surfaces → Tasks 11–12.
- **Spec deviation (minor):** `GmailStatusOut` omits the spec's optional `email?` field — populating it would require a live Gmail `getProfile` call per status poll; the field can be added later without breaking the contract. `GMAIL_CLIENT_MISSING` and `INVALID_DRAFT_TYPE` are new error codes the spec didn't enumerate.
- **Known verify-before-use points** (flagged inline): `tests/api/conftest.py` client fixture/data_dir pattern (Task 3), `html_to_text` signature (Task 4), `User.id`/`disabled_at` attributes (Task 7), `use_json_mode_for`/`ExtensibleModel` import paths + `Job.jd_text` (Task 9), dialog/popover primitives and JobModal layout (Tasks 11–12).
- **Type consistency:** `run_gmail_sync(engine, reporter, *, service, llm)` is consumed by Task 6's router and Task 7's scheduler with matching signatures; `EmailDraftOut` fields match the Task 8 table; `follow_up` kind string is shared via `FOLLOW_UP_KIND` but appears as a literal in web code (wire value).
