"""Source Manager wire schemas."""

from __future__ import annotations

from resume_agent.api.schemas.base import CamelModel


class SourceOut(CamelModel):
    id: str
    kind: str
    type: str
    display_name: str
    enabled: bool
    pullable: bool
    detail: str


class SourcePreviewIn(CamelModel):
    url: str
    label: str | None = None


class SourcePreviewOut(CamelModel):
    ok: bool
    url: str
    kind: str | None = None
    token: str | None = None
    label: str | None = None
    role_count: int | None = None
    error: str | None = None


class AddSourceIn(CamelModel):
    url: str
    label: str | None = None


class SetEnabledIn(CamelModel):
    enabled: bool
