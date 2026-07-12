from __future__ import annotations

import hmac
import time
from datetime import datetime, timezone
from typing import Literal, cast

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from resume_agent.api import auth
from resume_agent.api.deps import get_settings_dep
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.auth import (
    LinkTokenRequest,
    LinkTokenResponse,
    LoginRequest,
    MeResponse,
    RegisterRequest,
)
from resume_agent.config import Settings
from resume_agent.tenancy.context import new_user_id, require_context
from resume_agent.tenancy.secrets import hash_secret
from resume_agent.tenancy.system_db import InviteCode, User
from resume_agent.tenancy.workspace import provision_workspace

router = APIRouter(prefix="/auth", tags=["auth"])
link_router = APIRouter(prefix="/auth", tags=["auth"])
FAILED_LOGIN_DELAY_SECONDS = 0.05


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _rate_gate(request: Request, username: str) -> None:
    if request.app.state.login_limiter.blocked(username, _client_ip(request)):
        raise ApiException(
            429, "RATE_LIMITED", "Too many failed attempts; try again later"
        )


def _record_failure(request: Request, username: str) -> None:
    request.app.state.login_limiter.record_failure(username, _client_ip(request))


def _set_session_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(
        auth.SESSION_COOKIE,
        token,
        max_age=auth.SESSION_LIFETIME_SECONDS,
        httponly=True,
        secure=request.url.scheme == "https",
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
    system_engine = getattr(request.app.state, "system_engine", None)
    if system_engine is None:
        return _legacy_login(body, request, response, settings)
    _rate_gate(request, body.username)
    with Session(system_engine) as session:
        user = (
            session.execute(select(User).where(User.username == body.username))
            .scalars()
            .first()
        )
        password_hash = (
            user.password_hash if user is not None else auth.DUMMY_PASSWORD_HASH
        )
        password_valid = auth.verify_password(body.password, password_hash)
        if user is None or not password_valid:
            _record_failure(request, body.username)
            time.sleep(FAILED_LOGIN_DELAY_SECONDS)
            raise ApiException(401, "UNAUTHORIZED", "Invalid username or password")
        if user.disabled_at is not None:
            _record_failure(request, body.username)
            raise ApiException(403, "USER_DISABLED", "This account is disabled")
        if auth.hash_needs_upgrade(user.password_hash):
            user.password_hash = auth.hash_password(body.password)
        user.last_active_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(user)
        user_id, username, role, password_hash = (
            user.id,
            user.username,
            user.role,
            user.password_hash,
        )
    request.app.state.login_limiter.reset(body.username, _client_ip(request))
    _set_session_cookie(
        request,
        response,
        auth.issue_user_session(settings, user_id=user_id, password_hash=password_hash),
    )
    # The users.role CHECK constraint guarantees 'admin' | 'user' at the DB layer.
    return MeResponse(
        username=username, role=cast(Literal["admin", "user"], role), auth_required=True
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
        body.username.encode(), settings.auth_username.encode()
    )
    password_valid = auth.verify_password(body.password, settings.auth_password_hash)
    if not (username_valid and password_valid):
        time.sleep(FAILED_LOGIN_DELAY_SECONDS)
        raise ApiException(401, "UNAUTHORIZED", "Invalid username or password")
    _set_session_cookie(request, response, auth.issue_session(settings))
    return MeResponse(username=settings.auth_username, auth_required=True)


@router.post("/register", status_code=201)
def register(body: RegisterRequest, request: Request) -> MeResponse:
    system_engine = getattr(request.app.state, "system_engine", None)
    if system_engine is None:
        raise ApiException(
            400, "AUTH_NOT_CONFIGURED", "Registration requires multi-user mode"
        )
    _rate_gate(request, body.username)
    now = datetime.now(timezone.utc)
    try:
        with Session(system_engine) as session:
            session.execute(text("BEGIN IMMEDIATE"))
            invite = (
                session.execute(
                    select(InviteCode).where(
                        InviteCode.code_hash == hash_secret(body.invite_code)
                    )
                )
                .scalars()
                .first()
            )
            if invite is None or invite.revoked_at is not None:
                _record_failure(request, body.username)
                raise ApiException(400, "INVITE_INVALID", "Unknown invitation code")
            expires_at = invite.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= now:
                _record_failure(request, body.username)
                raise ApiException(400, "INVITE_EXPIRED", "Invitation code expired")
            if invite.used_at is not None:
                _record_failure(request, body.username)
                raise ApiException(400, "INVITE_USED", "Invitation code already used")
            if session.execute(
                select(User.id).where(User.username == body.username)
            ).first():
                _record_failure(request, body.username)
                raise ApiException(409, "USERNAME_TAKEN", "That username is taken")
            user = User(
                id=new_user_id(),
                username=body.username,
                password_hash=auth.hash_password(body.password),
                role="user",
            )
            session.add(user)
            invite.used_by = user.id
            invite.used_at = now
            session.commit()
            user_id = user.id
    except IntegrityError as error:
        _record_failure(request, body.username)
        raise ApiException(409, "USERNAME_TAKEN", "That username is taken") from error
    provision_workspace(
        request.app.state.data_dir,
        user_id,
        template_dir=request.app.state.template_config_dir,
    )
    request.app.state.login_limiter.reset(body.username, _client_ip(request))
    return MeResponse(username=body.username, role="user", auth_required=True)


@router.post("/logout")
def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return {"status": "ok"}


@router.get("/me")
def me(request: Request, settings: Settings = Depends(get_settings_dep)) -> MeResponse:
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
                token, settings, password_hash=user.password_hash
            )
            is None
        ):
            return MeResponse(auth_required=True)
        return MeResponse(
            username=user.username,
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
