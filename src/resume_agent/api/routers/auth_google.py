"""Identity-only Google sign-in and registration."""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from resume_agent.api import attempts, auth
from resume_agent.api.deps import get_settings_dep
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.auth_google import GoogleStartOut
from resume_agent.config import Settings
from resume_agent.mail import messages
from resume_agent.tenancy.context import new_user_id
from resume_agent.tenancy.secrets import hash_secret
from resume_agent.tenancy.system_db import InviteCode, User
from resume_agent.tenancy.workspace import provision_workspace, workspace_paths


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
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.url.netloc
    return f"{proto}://{host}/api/auth/google/callback"


def _build_flow(settings: Settings, redirect_uri: str) -> Any:
    from google_auth_oauthlib.flow import Flow

    return Flow.from_client_config(
        {
            "web": {
                "client_id": settings.google_oauth_client_id,
                "client_secret": settings.google_oauth_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=GOOGLE_SCOPES,
        redirect_uri=redirect_uri,
        autogenerate_code_verifier=False,
    )


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
    return GoogleStartOut(auth_url=url)


def _finish(target: str) -> RedirectResponse:
    return RedirectResponse(target)


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
            password_hash=user.password_hash,
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
    try:
        _require_client(settings)
        flow = _build_flow(settings, _redirect_uri(request))
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

        if parsed.mode != "register":
            session.rollback()
            logger.info("Google sign-in matched no account; routing to signup")
            return _finish(_signup_target(email, display_name))
        if not verified:
            session.rollback()
            return _failure(request, "/register?error=unverified_google")
        invite = (
            session.execute(
                select(InviteCode).where(InviteCode.code_hash == parsed.invite_hash)
            )
            .scalars()
            .first()
            if parsed.invite_hash
            else None
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
        )
        session.add(user)
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
