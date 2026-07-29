"""FastAPI dependencies: per-request DB session, settings, optional bearer auth."""

from __future__ import annotations

import hmac
from collections.abc import AsyncIterator, Iterator
from datetime import datetime, timezone

from fastapi import Depends, Header, Request
from sqlalchemy.engine import Engine
from sqlmodel import Session
from sqlalchemy import select
from sqlalchemy.orm import Session as SystemSession

from resume_agent.api.errors import ApiException
from resume_agent.config import Settings
from resume_agent.tenancy.context import UserContext, current_context, use_context
from resume_agent.tenancy.bootstrap import build_context
from resume_agent.tenancy.secrets import hash_secret
from resume_agent.tenancy.system_db import ApiToken, User
from resume_agent.tenancy.workspace import WorkspacePaths
from resume_agent.services.config_store import YamlConfigStore
from resume_agent.services.profile_documents import DocumentStore


def get_settings_dep(request: Request) -> Settings:
    context = current_context()
    return context.settings if context is not None else request.app.state.settings


def get_engine(request: Request) -> Engine:
    context = current_context()
    engine = context.engine if context is not None else request.app.state.engine
    # A real UserContext is only built with a registry-backed (always non-None)
    # engine; the field stays Optional to also cover engine-less test fixtures.
    assert engine is not None, "no engine bound to the active context or app state"
    return engine


def get_workspace_paths(request: Request) -> WorkspacePaths | None:
    context = current_context()
    return context.paths if context is not None else None


def get_data_dir(request: Request):
    paths = get_workspace_paths(request)
    return paths.root if paths is not None else request.app.state.data_dir


def get_profile_dir(request: Request):
    paths = get_workspace_paths(request)
    return (
        paths.profile_dir
        if paths is not None
        else request.app.state.data_dir / "profile"
    )


def get_interview_dir(request: Request):
    paths = get_workspace_paths(request)
    root = paths.root if paths is not None else request.app.state.data_dir
    return root / "interview"


def get_env_path(request: Request):
    paths = get_workspace_paths(request)
    return paths.secrets_env if paths is not None else request.app.state.env_path


def get_config_store(request: Request) -> YamlConfigStore:
    paths = get_workspace_paths(request)
    return (
        YamlConfigStore(paths.config_dir)
        if paths is not None
        else request.app.state.config_store
    )


def get_document_store(request: Request) -> DocumentStore:
    paths = get_workspace_paths(request)
    return (
        DocumentStore(paths.documents_dir)
        if paths is not None
        else request.app.state.document_store
    )


def get_session(request: Request) -> Iterator[Session]:
    """Yield a session bound to the app's engine; closed after the request."""
    engine = get_engine(request)
    with Session(engine) as session:
        yield session


def _authenticated_user(
    request: Request, *, link_purpose: str | None = None
) -> User | None:
    system_engine = getattr(request.app.state, "system_engine", None)
    if system_engine is None:
        return None
    from resume_agent.api import auth as auth_module

    user = None
    with SystemSession(system_engine, expire_on_commit=False) as session:
        cookie = request.cookies.get(auth_module.SESSION_COOKIE, "")
        user_id = auth_module.parse_session_user_id(cookie)
        if user_id:
            candidate = session.get(User, user_id)
            if candidate is not None and auth_module.verify_user_session(
                cookie,
                request.app.state.settings,
                password_hash=candidate.password_hash,
                epoch=candidate.session_epoch,
            ):
                user = candidate
        if user is None:
            scheme, separator, raw = request.headers.get("authorization", "").partition(
                " "
            )
            if separator and scheme.casefold() == "bearer" and raw.startswith("rat_"):
                token = (
                    session.execute(
                        select(ApiToken).where(
                            ApiToken.token_hash == hash_secret(raw.strip()),
                            ApiToken.revoked_at.is_(None),
                        )
                    )
                    .scalars()
                    .first()
                )
                if token is not None:
                    user = session.get(User, token.user_id)
                    now = datetime.now(timezone.utc)
                    token.last_used_at = now
                    if user is not None:
                        user.last_active_at = now
                    session.commit()
        if user is None and link_purpose is not None:
            user_id = auth_module.verify_link_token(
                request.query_params.get("token", ""),
                request.app.state.settings,
                purpose=link_purpose,
            )
            if user_id is not None:
                user = session.get(User, user_id)
        if user is not None:
            session.expunge(user)
    return user


async def _activate_user_context(
    request: Request, *, link_purpose: str | None = None
) -> AsyncIterator[UserContext | None]:
    system_engine = getattr(request.app.state, "system_engine", None)
    if system_engine is None:
        yield None
        return
    user = _authenticated_user(request, link_purpose=link_purpose)
    if user is None:
        raise ApiException(401, "UNAUTHORIZED", "Missing or invalid credentials")
    if user.disabled_at is not None:
        raise ApiException(403, "USER_DISABLED", "This account is disabled")
    context = build_context(
        user,
        request.app.state.data_dir,
        request.app.state.settings,
        request.app.state.engine_registry,
        system_engine=system_engine,
        template_dir=request.app.state.template_config_dir,
    )
    request.app.state.run_manager.register_root(context.paths.runs_root)
    with use_context(context):
        yield context


async def get_user_context(request: Request) -> AsyncIterator[UserContext | None]:
    """Authenticate session/PAT and activate the request's tenant context."""
    async for context in _activate_user_context(request):
        yield context


async def get_sse_user_context(request: Request) -> AsyncIterator[UserContext | None]:
    """Authenticate SSE by normal credentials or a purpose-bound short token."""
    async for context in _activate_user_context(request, link_purpose="sse"):
        yield context


async def get_download_user_context(
    request: Request,
) -> AsyncIterator[UserContext | None]:
    """Authenticate a selected download by credentials or a short capability."""
    async for context in _activate_user_context(request, link_purpose="download"):
        yield context


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
    if getattr(request.app.state, "system_engine", None) is not None:
        return
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


def require_admin() -> UserContext:
    from resume_agent.tenancy.context import require_context

    context = require_context()
    if not context.is_admin:
        raise ApiException(403, "FORBIDDEN", "Admin role required")
    return context


def refresh_app_settings(app, fresh: Settings) -> None:
    """Keep startup/platform fields when volume-backed settings are refreshed."""
    if current_context() is not None:
        return
    app.state.settings = fresh.model_copy(
        update={
            "db_url": app.state.db_url,
            "api_token": app.state.settings.api_token,
            "auth_username": app.state.settings.auth_username,
            "auth_password_hash": app.state.settings.auth_password_hash,
            "session_secret": app.state.settings.session_secret,
            "browser_enabled": app.state.settings.browser_enabled,
        }
    )
