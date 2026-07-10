"""Public login/logout/session-state endpoints for the single owner account."""

from __future__ import annotations

import hmac
import time

from fastapi import APIRouter, Depends, Request, Response

from resume_agent.api import auth
from resume_agent.api.deps import get_settings_dep
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.auth import LoginRequest, MeResponse
from resume_agent.config import Settings

router = APIRouter(prefix="/auth", tags=["auth"])
FAILED_LOGIN_DELAY_SECONDS = 1.0


@router.post("/login")
def login(
    body: LoginRequest,
    response: Response,
    settings: Settings = Depends(get_settings_dep),
) -> MeResponse:
    if not auth.session_auth_configured(settings):
        raise ApiException(400, "AUTH_NOT_CONFIGURED", "Session auth is not configured")

    username_ok = hmac.compare_digest(
        body.username.encode(), settings.auth_username.encode()
    )
    password_ok = auth.verify_password(body.password, settings.auth_password_hash)
    if not (username_ok and password_ok):
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
    return MeResponse(username=settings.auth_username, auth_required=True)


@router.post("/logout")
def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return {"status": "ok"}


@router.get("/me")
def me(
    request: Request,
    settings: Settings = Depends(get_settings_dep),
) -> MeResponse:
    if not auth.session_auth_configured(settings):
        return MeResponse(auth_required=False)
    token = request.cookies.get(auth.SESSION_COOKIE, "")
    return MeResponse(
        username=auth.verify_session(token, settings),
        auth_required=True,
    )
