"""Gmail account connection: OAuth web flow + status + disconnect.

The callback is unguarded — Google's top-level redirect may not carry
SameSite cookies — and authenticates via the signed `state` instead
(link token, purpose "gmail-oauth"). In no-tenancy local mode a random
in-memory state (app.state.gmail_oauth_states) replaces the signature.
"""

from __future__ import annotations

import logging
import secrets as pysecrets
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from resume_tailor_harness.api import auth as auth_module
from resume_tailor_harness.api.deps import get_data_dir, get_settings_dep
from resume_tailor_harness.api.errors import ApiException
from resume_tailor_harness.api.public_url import public_url
from resume_tailor_harness.api.schemas.gmail import GmailConnectOut, GmailStatusOut
from resume_tailor_harness.config import Settings, get_settings
from resume_tailor_harness.gmail import auth as gmail_auth
from resume_tailor_harness.gmail.errors import GmailScopeMissing
from resume_tailor_harness.tenancy.context import current_context, use_context

logger = logging.getLogger(__name__)

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
    # PKCE off: connect and callback build independent Flow objects, so an
    # auto-generated code_verifier can't survive to the token exchange (Google
    # would reject with invalid_grant "Missing code verifier"). This is a
    # confidential web client — the client_secret authenticates fetch_token.
    return Flow.from_client_config(
        client_config,
        scopes=gmail_auth.GMAIL_SCOPES,
        redirect_uri=redirect_uri,
        autogenerate_code_verifier=False,
    )


def _granted_scopes(token: Any) -> list[str]:
    """Scopes Google says it granted, falling back to what we asked for.

    RFC 6749 makes the response ``scope`` optional when it equals the request,
    so an absent value means "unchanged", not "nothing granted".
    """
    raw = (token or {}).get("scope")
    if not raw:
        return list(gmail_auth.GMAIL_SCOPES)
    return raw.split() if isinstance(raw, str) else list(raw)


def _exchange_token(flow: Any, code: str) -> str:
    """Trade the code for credentials JSON carrying the *granted* scopes.

    Connect asks for incremental authorization, so Google returns the union of
    every scope this OAuth client already holds — the Gmail pair plus the
    identity scopes from Google sign-in, which shares the client. oauthlib
    enforces RFC 6749 section 3.3 as a raw set inequality and raises a bare
    ``Warning`` from inside ``fetch_token`` on *any* difference, so it cannot
    tell that harmless superset from a grant that is missing what we asked for.
    Clearing the session scope drops that blanket comparison; the distinction it
    failed to make is drawn explicitly below.

    The session scope is then restored to what was actually granted, because
    ``Flow.credentials`` copies it into ``Credentials.scopes`` and that list is
    the only scope record ``to_json`` persists — the one ``has_compose`` later
    reads. Leaving the requested pair there would claim compose access the user
    may have withheld on Google's granular consent screen.
    """
    session = flow.oauth2session
    session.scope = None
    flow.fetch_token(code=code)
    granted = _granted_scopes(session.token)
    if gmail_auth.SCOPE_READONLY not in granted:
        raise GmailScopeMissing(
            "Gmail access was not granted — approve the Gmail permissions to connect."
        )
    session.scope = granted
    return flow.credentials.to_json()


def _redirect_uri(request: Request) -> str:
    return public_url(request, "/api/gmail/callback")


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
    settings = get_settings_dep(request)
    _require_client(settings)
    flow = _build_flow(settings, _redirect_uri(request))
    extra: dict[str, str] = {"include_granted_scopes": "true"}
    email = _account_email(request)
    if email:
        extra["login_hint"] = email
    url, _state = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        state=_issue_state(request),
        **extra,
    )
    return GmailConnectOut(auth_url=url)


def _account_email(request: Request) -> str:
    context = current_context()
    engine = getattr(request.app.state, "system_engine", None)
    if context is None or engine is None:
        return ""
    from sqlalchemy.orm import Session as SystemSession

    from resume_tailor_harness.tenancy.system_db import User

    with SystemSession(engine) as session:
        user = session.get(User, context.user_id)
        return user.email or "" if user is not None else ""


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

    from resume_tailor_harness.tenancy.system_db import User

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
            gmail_auth.save_token_json(
                _exchange_token(flow, code), request.app.state.data_dir
            )
        else:
            from resume_tailor_harness.tenancy.bootstrap import build_context

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
                gmail_auth.save_token_json(_exchange_token(flow, code))
    except ApiException as exc:
        logger.exception(
            "Gmail callback rejected (config/client): %s %s", exc.code, exc.message
        )
        return _finish("error")
    except GmailScopeMissing:
        # Distinct from the branch below: the exchange itself succeeded, the
        # user just withheld Gmail access on the consent screen.
        logger.warning("Gmail callback: consent granted no Gmail access")
        return _finish("error")
    except Exception:  # noqa: BLE001 — never render a raw OAuth error page
        logger.exception("Gmail callback token exchange failed")
        return _finish("error")
    return _finish("connected")


def _status(request: Request) -> GmailStatusOut:
    creds = gmail_auth.load_credentials(get_data_dir(request))
    context = current_context()
    base_client = request.app.state.settings.google_oauth_client_id
    effective_client = get_settings_dep(request).google_oauth_client_id
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
