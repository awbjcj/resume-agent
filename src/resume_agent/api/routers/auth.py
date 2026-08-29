from __future__ import annotations

import hmac
import time
from datetime import datetime, timezone
from typing import Literal, cast

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from resume_agent.api import attempts, auth
from resume_agent.api.deps import get_settings_dep
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.auth import (
    LinkTokenRequest,
    LinkTokenResponse,
    LoginRequest,
    MeResponse,
)
from resume_agent.config import Settings
from resume_agent.tenancy.context import require_context
from resume_agent.tenancy.system_db import User

router = APIRouter(prefix="/auth", tags=["auth"])
link_router = APIRouter(prefix="/auth", tags=["auth"])
FAILED_LOGIN_DELAY_SECONDS = 0.05


def _local_me(request: Request) -> MeResponse:
    context = getattr(request.app.state, "default_context", None)
    if context is None:
        return MeResponse(auth_required=False)
    return MeResponse(
        username=context.username,
        role=cast(Literal["admin", "user"], context.role),
        auth_required=False,
    )


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _rate_gate(request: Request, identifier: str) -> None:
    engine = getattr(request.app.state, "system_engine", None)
    if engine is not None and attempts.blocked(
        engine, email=identifier, ip=_client_ip(request)
    ):
        raise ApiException(
            429, "RATE_LIMITED", "Too many failed attempts; try again later"
        )


def _record_failure(request: Request, identifier: str) -> None:
    engine = getattr(request.app.state, "system_engine", None)
    if engine is not None and not attempts.record_failure(
        engine, email=identifier, ip=_client_ip(request)
    ):
        raise ApiException(
            429, "RATE_LIMITED", "Too many failed attempts; try again later"
        )


def resolve_login_user(session: Session, identifier: str) -> User | None:
    return (
        session.execute(
            select(User).where(
                (User.email == identifier)
                | (User.email.is_(None) & (User.username == identifier))
            )
        )
        .scalars()
        .first()
    )


@router.post("/login")
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings_dep),
) -> MeResponse:
    if request.app.state.app_mode == "local":
        return _local_me(request)
    system_engine = getattr(request.app.state, "system_engine", None)
    if system_engine is None:
        return _legacy_login(body, request, response, settings)
    _rate_gate(request, body.identifier)
    with Session(system_engine) as session:
        user = resolve_login_user(session, body.identifier)
        password_hash = (
            user.password_hash if user is not None else auth.DUMMY_PASSWORD_HASH
        )
        password_valid = auth.verify_password(body.password, password_hash)
        now = datetime.now(timezone.utc)
        locked = user is not None and attempts.is_locked(user, now)
        if user is None or not password_valid or locked:
            if user is not None and not locked:
                attempts.register_lockout(user, now)
                session.commit()
            _record_failure(request, body.identifier)
            time.sleep(FAILED_LOGIN_DELAY_SECONDS)
            raise ApiException(401, "UNAUTHORIZED", "Invalid username or password")
        if user.disabled_at is not None:
            _record_failure(request, body.identifier)
            raise ApiException(403, "USER_DISABLED", "This account is disabled")
        if auth.hash_needs_upgrade(user.password_hash):
            user.password_hash = auth.hash_password(body.password)
        attempts.clear_lockout(user)
        user.last_active_at = now
        session.commit()
        session.refresh(user)
        user_id, username, role, epoch, email, verified, google_sub = (
            user.id,
            user.username,
            user.role,
            user.session_epoch,
            user.email,
            user.email_verified_at,
            user.google_sub,
        )
    attempts.reset(system_engine, email=body.identifier, ip=_client_ip(request))
    auth.set_session_cookie(
        request,
        response,
        auth.issue_user_session(settings, user_id=user_id, epoch=epoch),
    )
    # The users.role CHECK constraint guarantees 'admin' | 'user' at the DB layer.
    return MeResponse(
        username=username,
        email=email,
        email_verified=verified is not None,
        needs_email=email is None,
        google_linked=google_sub is not None,
        role=cast(Literal["admin", "user"], role),
        auth_required=True,
    )


def _legacy_login(
    body: LoginRequest,
    request: Request,
    response: Response,
    settings: Settings,
) -> MeResponse:
    if not auth.session_auth_configured(settings):
        raise ApiException(400, "AUTH_NOT_CONFIGURED", "Session auth is not configured")
    username_valid = hmac.compare_digest(
        body.identifier.encode(), settings.auth_username.encode()
    )
    password_valid = auth.verify_password(body.password, settings.auth_password_hash)
    if not (username_valid and password_valid):
        time.sleep(FAILED_LOGIN_DELAY_SECONDS)
        raise ApiException(401, "UNAUTHORIZED", "Invalid username or password")
    auth.set_session_cookie(request, response, auth.issue_session(settings))
    return MeResponse(username=settings.auth_username, auth_required=True)


@router.post("/logout")
def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return {"status": "ok"}


@router.get("/me")
def me(request: Request, settings: Settings = Depends(get_settings_dep)) -> MeResponse:
    if request.app.state.app_mode == "local":
        return _local_me(request)
    system_engine = getattr(request.app.state, "system_engine", None)
    token = request.cookies.get(auth.SESSION_COOKIE, "")
    if system_engine is None:
        if not auth.session_auth_configured(settings):
            return MeResponse(auth_required=False)
        return MeResponse(
            username=auth.verify_session(token, settings), auth_required=True
        )
    user_id = auth.parse_session_user_id(token)
    if user_id is None:
        return MeResponse(auth_required=True)
    with Session(system_engine) as session:
        user = session.get(User, user_id)
        if (
            user is None
            or user.disabled_at is not None
            or auth.verify_user_session(
                token,
                settings,
                epoch=user.session_epoch,
            )
            is None
        ):
            return MeResponse(auth_required=True)
        return MeResponse(
            username=user.username,
            email=user.email,
            email_verified=user.email_verified_at is not None,
            needs_email=user.email is None,
            google_linked=user.google_sub is not None,
            role=cast(Literal["admin", "user"], user.role),
            auth_required=True,
        )


@link_router.post("/link-token")
def mint_link_token(
    body: LinkTokenRequest,
    settings: Settings = Depends(get_settings_dep),
) -> LinkTokenResponse:
    context = require_context()
    return LinkTokenResponse(
        token=auth.issue_link_token(
            settings, user_id=context.user_id, purpose=body.purpose
        ),
        expires_in_seconds=auth.LINK_TOKEN_TTL_SECONDS,
    )
