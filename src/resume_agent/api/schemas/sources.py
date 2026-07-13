"""Source Manager wire schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from resume_agent.api.schemas.base import CamelModel


class SourceOut(CamelModel):
    id: str
    kind: str
    type: str
    display_name: str
    enabled: bool
    pullable: bool
    detail: str
    limit: int | None = None


SourceProvider = Literal[
    "auto",
    "greenhouse",
    "lever",
    "ashby",
    "workday",
    "smartrecruiters",
    "workable",
    "recruitee",
    "personio",
    "breezy",
    "jazzhr",
    "bamboohr",
]


class SourceConnectionIn(CamelModel):
    provider: SourceProvider = "auto"
    url: str | None = None
    token: str | None = None
    tenant: str | None = None
    datacenter: str | None = None
    site: str | None = None
    country: Literal["com", "de"] = "com"
    label: str | None = None

class SourcePreviewIn(SourceConnectionIn):
    pass


class SourcePreviewOut(CamelModel):
    ok: bool
    url: str
    kind: str | None = None
    token: str | None = None
    label: str | None = None
    role_count: int | None = None
    error: str | None = None


class AddSourceIn(SourceConnectionIn):
    pass


class SourcePatchIn(CamelModel):
    enabled: bool | None = None
    limit: int | None = Field(default=None, ge=1)
