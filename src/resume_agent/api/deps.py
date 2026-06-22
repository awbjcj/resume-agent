"""FastAPI dependencies: per-request DB session, settings, optional bearer auth."""

from __future__ import annotations

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
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings_dep),
) -> None:
    """No-op when no api_token is configured; else enforce a bearer match."""
    if not settings.api_token:
        return
    expected = f"Bearer {settings.api_token}"
    if authorization != expected:
        raise ApiException(401, "UNAUTHORIZED", "Missing or invalid bearer token")
