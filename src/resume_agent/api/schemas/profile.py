"""Profile document + build wire schemas."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AnyHttpUrl, Field, StringConstraints

from resume_agent.api.schemas.base import CamelModel
from resume_agent.profile.corpus import SourceMode, SourceOrigin


class DocumentOut(CamelModel):
    id: str
    filename: str
    doc_type: str
    size_bytes: int
    uploaded_at: str


class SourceOut(CamelModel):
    id: str
    filename: str
    mode: SourceMode
    primary: bool
    anchor: str | None = None
    added_at: str
    fragment_status: str
    origin: SourceOrigin = "upload"


class SourcePatch(CamelModel):
    mode: SourceMode | None = None
    anchor: str | None = None
    primary: bool | None = None


class SkeletonEntryOut(CamelModel):
    id: str
    kind: str
    label: str


class NoteIn(CamelModel):
    title: str = Field(default="", max_length=200)
    text: str = Field(min_length=1, max_length=100_000)


class UrlIn(CamelModel):
    url: AnyHttpUrl


class MatrixRowOut(CamelModel):
    key: str
    display: str
    category: str | None = None
    group: str | None = None
    group_source: Literal["correction", "override", "taxonomy"] | None = None
    inferred: bool = False
    strength: float = 0.0
    last_used: str | None = None


class SkillGroupOut(CamelModel):
    slug: str
    label: str


class MatrixOut(CamelModel):
    generated_at: str = ""
    groups: list[SkillGroupOut] = Field(default_factory=list)
    rows: list[MatrixRowOut] = Field(default_factory=list)


class SkillEntryOut(CamelModel):
    id: str
    name: str
    category: Literal["hard", "soft", "domain"] | None = None


class AddSkillIn(CamelModel):
    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]
    category: Literal["hard", "soft", "domain"] | None = None


class AddAliasIn(CamelModel):
    alias: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]


class SetGroupIn(CamelModel):
    group: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)
    ]


class ManualEntryOut(CamelModel):
    id: str
    kind: Literal["new_skill", "alias"]
    added_at: str
    name: str | None = None
    category: Literal["hard", "soft", "domain"] | None = None
    alias_text: str | None = None
    target_skill_display: str | None = None


class SuppressedSkillOut(CamelModel):
    token: str
    display: str
    added_at: str
