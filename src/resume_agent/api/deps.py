"""FastAPI dependencies: per-request DB session, settings, optional bearer auth."""

from __future__ import annotations

import hmac
from collections.abc import Iterator

from fastapi import Depends, Header, Request
from sqlmodel import Session

from resume_agent.api.errors import ApiException
from resume_agent.config import Settings, get_settings


def get_settings_dep() -> Settings:
    return get_settings()


def get_session(request: Request) -> Iterator[Session]:
    """Yield a session bound to the app's engine; closed after the request."""
    engine = request.app.state.engine
    with Session(engine) as session:
        yield session


def require_token(
    request: Request,
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings_dep),
) -> None:
    """Accept a valid session cookie or the existing bearer/query token.

    Accepts the token either in the ``Authorization: Bearer`` header or, as a
    fallback for clients that cannot set headers (``EventSource`` SSE, ``<a>``
    downloads), in a ``?token=`` query param. The query param is read off the raw
    request (not declared as a FastAPI ``Query``) so it stays out of the OpenAPI
    schema for every guarded route. Note: query-param tokens can appear in access
    logs — acceptable for a localhost single-user tool.
    """
    from resume_agent.api.auth import (
        SESSION_COOKIE,
        session_auth_configured,
        verify_session,
    )

    session_configured = session_auth_configured(settings)
    if session_configured and verify_session(
        request.cookies.get(SESSION_COOKIE, ""), settings
    ):
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
    if session_configured or settings.api_token:
        raise ApiException(401, "UNAUTHORIZED", "Missing or invalid credentials")


def get_run_manager(request: Request):
    return request.app.state.run_manager


def refresh_app_settings(app, fresh: Settings) -> None:
    """Keep startup/platform fields when volume-backed settings are refreshed."""
    app.state.settings = fresh.model_copy(update={
        "db_url": app.state.db_url,
        "api_token": app.state.settings.api_token,
        "auth_username": app.state.settings.auth_username,
        "auth_password_hash": app.state.settings.auth_password_hash,
        "session_secret": app.state.settings.session_secret,
        "browser_enabled": app.state.settings.browser_enabled,
    })
