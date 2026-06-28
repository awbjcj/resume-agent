"""Gap-closing advisor API schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AnyHttpUrl, ConfigDict, Field, field_validator

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


class SuggestionTarget(CamelModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["skill", "theme"]
    key: str = Field(min_length=1, max_length=200)

    @field_validator("key", mode="before")
    @classmethod
    def trim_key(cls, value):
        return value.strip() if isinstance(value, str) else value


class SuggestionRunsRequest(CamelModel):
    model_config = ConfigDict(extra="forbid")

    targets: list[SuggestionTarget] = Field(min_length=1, max_length=25)


class SuggestionRunAcceptedOut(CamelModel):
    outcome: Literal["accepted"]
    kind: Literal["skill", "theme"]
    key: str
    run_id: str


class SuggestionRunNotFoundOut(CamelModel):
    outcome: Literal["not_found"]
    kind: Literal["skill", "theme"]
    key: str


SuggestionRunResultOut = Annotated[
    SuggestionRunAcceptedOut | SuggestionRunNotFoundOut,
    Field(discriminator="outcome"),
]


class SuggestionRunsOut(CamelModel):
    results: list[SuggestionRunResultOut]
