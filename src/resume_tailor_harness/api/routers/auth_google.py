"""Identity-only Google sign-in and registration."""

from __future__ import annotations

import hmac
import logging
import shutil
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, or_, select, text
from sqlalchemy.orm import Session

from resume_tailor_harness.api import attempts, auth
from resume_tailor_harness.api.deps import get_settings_dep
from resume_tailor_harness.api.errors import ApiException
from resume_tailor_harness.api.public_url import public_url
from resume_tailor_harness.api.schemas.auth_google import GoogleStartOut
from resume_tailor_harness.config import Settings
from resume_tailor_harness.mail import messages
from resume_tailor_harness.tenancy.context import new_user_id
from resume_tailor_harness.tenancy.quotas import assign_new_member
from resume_tailor_harness.tenancy.secrets import hash_secret
from resume_tailor_harness.tenancy.system_db import InviteCode, OAuthFlow, User
from resume_tailor_harness.tenancy.workspace import provision_workspace, workspace_paths


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth/google", tags=["auth"])
callback_router = APIRouter(prefix="/auth/google", tags=["auth"])
GOOGLE_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _require_client(settings: Settings) -> None:
    if not (settings.google_oauth_client_id and settings.google_oauth_client_secret):
        raise ApiException(
            409,
            "GOOGLE_CLIENT_MISSING",
            "No Google OAuth client is configured",
        )


def _redirect_uri(request: Request) -> str:
    return public_url(request, "/api/auth/google/callback")


def _build_flow(
    settings: Settings,
    redirect_uri: str,
    *,
    code_verifier: str | None = None,
) -> Any:
    from google_auth_oauthlib.flow import Flow

    return Flow.from_client_config(
        {
            "web": {
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/v2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=GOOGLE_SCOPES,
        redirect_uri=redirect_uri,
        code_verifier=code_verifier,
        autogenerate_code_verifier=code_verifier is None,
    )


def _store_oauth_flow(engine: Any, *, state: str, verifier: str) -> str:
    """Persist the PKCE verifier behind a one-time, browser-bound opaque handle."""
    if engine is None:
        raise ApiException(503, "OAUTH_UNAVAILABLE", "Google sign-in is unavailable")
    if not auth._valid_oauth_pkce_verifier(verifier):
        raise ValueError("invalid OAuth PKCE verifier")
    now = datetime.now(timezone.utc)
    flow_cookie = auth.issue_oauth_flow_cookie()
    with Session(engine) as session:
        # One writer transaction makes consume-once semantics work across workers.
        session.execute(text("BEGIN IMMEDIATE"))
        session.execute(delete(OAuthFlow).where(OAuthFlow.expires_at <= now))
        session.add(
            OAuthFlow(
                id=flow_cookie,
                state=state,
                pkce_verifier=verifier,
                expires_at=now + timedelta(seconds=auth.OAUTH_STATE_TTL_SECONDS),
            )
        )
        session.commit()
    return flow_cookie


def _consume_oauth_flow(
    engine: Any,
    *,
    flow_cookie: str | None,
    state: str,
) -> str | None:
    """Atomically consume an opaque flow handle only for its signed OAuth state."""
    if engine is None or flow_cookie is None or not state:
        return None
    now = datetime.now(timezone.utc)
    try:
        with Session(engine) as session:
            session.execute(text("BEGIN IMMEDIATE"))
            flow = session.get(OAuthFlow, flow_cookie)
            if flow is None:
                session.rollback()
                return None
            session.delete(flow)
            session.commit()
    except Exception:  # noqa: BLE001 - reject callback if its one-time state cannot be consumed
        logger.exception("Unable to consume Google OAuth flow")
        return None
    expires_at = flow.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if (
        expires_at <= now
        or not hmac.compare_digest(flow.state, state)
        or not auth._valid_oauth_pkce_verifier(flow.pkce_verifier)
    ):
        return None
    return flow.pkce_verifier


def _verify_id_token(flow: Any, settings: Settings) -> dict[str, Any]:
    from google.auth.transport import requests as google_requests
    from google.oauth2 import id_token

    return dict(
        id_token.verify_oauth2_token(
            flow.credentials.id_token,
            google_requests.Request(),
            settings.google_oauth_client_id,
        )
    )


@router.get("/start", response_model=GoogleStartOut)
def google_start(
    request: Request,
    response: Response,
    mode: str = Query(default="login", pattern="^(login|register)$"),
    invite: str = Query(default=""),
) -> GoogleStartOut:
    settings = get_settings_dep(request)
    _require_client(settings)
    engine = getattr(request.app.state, "system_engine", None)
    if engine is not None and not attempts.consume(
        engine, email="", ip=_client_ip(request), scopes=attempts.IP_ONLY
    ):
        raise ApiException(429, "RATE_LIMITED", "Too many attempts; try again later")
    state = auth.issue_oauth_state(
        settings,
        mode=mode,
        invite_hash=hash_secret(invite) if invite else "",
    )
    flow = _build_flow(settings, _redirect_uri(request))
    url, _state = flow.authorization_url(prompt="select_account", state=state)
    verifier = str(flow.code_verifier or "")
    if not verifier:
        raise ApiException(500, "OAUTH_START_FAILED", "Google sign-in could not start")
    flow_cookie = _store_oauth_flow(engine, state=state, verifier=verifier)
    auth.set_oauth_flow_cookie(request, response, flow_cookie=flow_cookie)
    return GoogleStartOut(auth_url=url)


def _finish(target: str) -> RedirectResponse:
    response = RedirectResponse(target)
    auth.clear_oauth_flow_cookies(response)
    return response


def _failure(request: Request, target: str) -> RedirectResponse:
    engine = getattr(request.app.state, "system_engine", None)
    if engine is not None:
        attempts.consume(
            engine, email="", ip=_client_ip(request), scopes=attempts.IP_ONLY
        )
    return _finish(target)


def _signup_target(email: str, name: str) -> str:
    """Carry the Google identity to the signup form as an editable prefill.

    Deliberately *not* a link: nothing here sets ``google_sub``, because a query
    string is not proof of anything. The emailed verification code establishes
    ownership of whatever address is submitted; a later Google sign-in then
    links by verified email through the ``by_email`` branch above.
    """
    query = {"from": "google", "email": email}
    if name:
        query["name"] = name
    return f"/register?{urlencode(query)}"


def _sign_in(request: Request, settings: Settings, user: User) -> RedirectResponse:
    response = _finish("/")
    auth.set_session_cookie(
        request,
        response,
        auth.issue_user_session(
            settings,
            user_id=user.id,
            epoch=user.session_epoch,
        ),
    )
    return response


def _available_username(session: Session, preferred: str, user_id: str) -> str:
    base = preferred.strip()[:64] or f"google-{user_id}"
    if session.execute(select(User.id).where(User.username == base)).scalar() is None:
        return base
    suffix = f"-{user_id[:6]}"
    return f"{base[: 64 - len(suffix)]}{suffix}"


@callback_router.get("/callback", include_in_schema=False)
def google_callback(
    request: Request, code: str = "", state: str = "", error: str = ""
) -> RedirectResponse:
    if error:
        return _failure(request, "/login?error=denied")
    settings = request.app.state.settings
    parsed = auth.verify_oauth_state(state, settings)
    if parsed is None:
        return _failure(request, "/login?error=invalid_state")
    engine = getattr(request.app.state, "system_engine", None)
    if engine is None:
        return _failure(request, "/login?error=unavailable")
    verifier = _consume_oauth_flow(
        engine,
        flow_cookie=auth.oauth_flow_cookie(request),
        state=state,
    )
    if verifier is None:
        return _failure(request, "/login?error=invalid_state")
    try:
        _require_client(settings)
        flow = _build_flow(
            settings,
            _redirect_uri(request),
            code_verifier=verifier,
        )
        flow.fetch_token(code=code)
        claims = _verify_id_token(flow, settings)
    except Exception:  # noqa: BLE001 - OAuth errors must return a safe page
        logger.exception("Google callback exchange failed")
        return _failure(request, "/login?error=exchange_failed")

    subject = str(claims.get("sub") or "")
    email = str(claims.get("email") or "").strip().casefold()
    verified = claims.get("email_verified") is True
    # Capped to RegisterRequest.display_name's max_length so a long Google name
    # cannot prefill the form with a value the register endpoint would reject.
    display_name = str(claims.get("name") or "").strip()[:64]
    if not subject or not email:
        return _failure(request, "/login?error=exchange_failed")
    # A login-mode request may become a first-time signup when registration is
    # open. Only spend the global signup budget when neither Google identity nor
    # verified email currently belongs to an account; returning users must never
    # be locked out because the signup budget is exhausted.
    with Session(engine) as lookup:
        known_user = (
            lookup.execute(
                select(User.id).where(
                    or_(User.google_sub == subject, User.email == email)
                )
            )
            .scalars()
            .first()
        )
    may_create = parsed.mode == "register" or settings.registration_mode == "open"
    if known_user is None and may_create and not verified:
        return _failure(request, "/register?error=unverified_google")
    if (
        known_user is None
        and may_create
        and not attempts.consume_global_signup(
            engine,
            limit=settings.global_daily_signup_limit,
        )
    ):
        return _failure(request, "/register?error=rate_limited")

    now = datetime.now(timezone.utc)
    with Session(engine, expire_on_commit=False) as session:
        session.execute(text("BEGIN IMMEDIATE"))
        by_sub = (
            session.execute(select(User).where(User.google_sub == subject))
            .scalars()
            .first()
        )
        if by_sub is not None:
            if by_sub.disabled_at is not None:
                session.rollback()
                return _failure(request, "/login?error=disabled")
            attempts.clear_lockout(by_sub)
            by_sub.last_active_at = now
            session.commit()
            attempts.reset(engine, email=email, ip=_client_ip(request))
            return _sign_in(request, settings, by_sub)

        by_email = (
            session.execute(select(User).where(User.email == email)).scalars().first()
        )
        if by_email is not None:
            if not verified:
                session.rollback()
                return _failure(request, "/login?error=unverified_google")
            if by_email.disabled_at is not None:
                session.rollback()
                return _failure(request, "/login?error=disabled")
            if by_email.google_sub is not None:
                session.rollback()
                return _failure(request, "/login?error=google_conflict")
            by_email.google_sub = subject
            by_email.email_verified_at = by_email.email_verified_at or now
            by_email.last_active_at = now
            attempts.clear_lockout(by_email)
            session.commit()
            attempts.reset(engine, email=email, ip=_client_ip(request))
            notice = messages.google_linked(settings.app_base_url)
            request.app.state.mailer.notify(
                to=email, subject=notice.subject, body=notice.body
            )
            return _sign_in(request, settings, by_email)

        if parsed.mode != "register" and settings.registration_mode != "open":
            session.rollback()
            logger.info("Google sign-in matched no account; routing to signup")
            return _finish(_signup_target(email, display_name))
        if not verified:
            session.rollback()
            return _failure(request, "/register?error=unverified_google")
        if settings.registration_mode == "closed":
            session.rollback()
            return _failure(request, "/register?error=registration_closed")
        invite = None
        if settings.registration_mode == "invite":
            invite = (
                session.execute(
                    select(InviteCode).where(InviteCode.code_hash == parsed.invite_hash)
                )
                .scalars()
                .first()
            )
            expires = None if invite is None else invite.expires_at
            if expires is not None and expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if (
                invite is None
                or invite.revoked_at is not None
                or invite.used_at is not None
                or expires is None
                or expires <= now
            ):
                session.rollback()
                return _failure(request, "/register?error=invite_invalid")

        user_id = new_user_id()
        user = User(
            id=user_id,
            username=_available_username(
                session, display_name or email.partition("@")[0], user_id
            ),
            email=email,
            email_verified_at=now,
            google_sub=subject,
            password_hash="",
            role="user",
            last_active_at=now,
            shared_key_access=True,
            weekly_token_budget=(
                settings.open_signup_weekly_token_budget
                if settings.registration_mode == "open"
                else None
            ),
            max_active_jobs=(
                settings.open_signup_max_active_jobs
                if settings.registration_mode == "open"
                else None
            ),
            max_concurrent_runs=(
                settings.open_signup_max_concurrent_runs
                if settings.registration_mode == "open"
                else None
            ),
        )
        session.add(user)
        assign_new_member(session, user.id, now=now)
        if invite is not None:
            invite.used_by = user.id
            invite.used_at = now
        workspace = workspace_paths(request.app.state.data_dir, user.id).root
        try:
            provision_workspace(
                request.app.state.data_dir,
                user.id,
                template_dir=request.app.state.template_config_dir,
            )
            session.commit()
        except Exception:  # noqa: BLE001 - compensate both database and filesystem
            session.rollback()
            shutil.rmtree(workspace, ignore_errors=True)
            logger.exception("Google registration failed")
            return _failure(request, "/register?error=conflict")
        attempts.reset(engine, email=email, ip=_client_ip(request))
        return _sign_in(request, settings, user)
