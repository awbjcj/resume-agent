"""Gap-closing advisor API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import AnyHttpUrl

from resume_agent.api.schemas.base import CamelModel


class RepoOut(CamelModel):
    name: str
    url: AnyHttpUrl
    why: str
    stars: int | None = None
    description: str | None = None


class ResourceOut(CamelModel):
    title: str
    url: AnyHttpUrl
    kind: Literal["course", "doc", "tutorial"]


class ProjectOut(CamelModel):
    title: str
    summary: str
    skills_demonstrated: list[str]


class SuggestionOut(CamelModel):
    kind: Literal["skill", "theme"]
    key: str
    repos: list[RepoOut]
    resources: list[ResourceOut]
    project: ProjectOut | None = None
    bridge: str
    citations: list[AnyHttpUrl]
    generated_at: datetime


class SuggestionEnvelope(CamelModel):
    suggestion: SuggestionOut | None = None
    stale: bool = False
