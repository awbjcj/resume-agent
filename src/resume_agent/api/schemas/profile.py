"""Profile document + build wire schemas."""

from __future__ import annotations

from resume_agent.api.schemas.base import CamelModel


class DocumentOut(CamelModel):
    id: str
    filename: str
    doc_type: str
    size_bytes: int
    uploaded_at: str


class SourceOut(CamelModel):
    id: str
    filename: str
    mode: str
    primary: bool
    anchor: str | None = None
    added_at: str
    fragment_status: str


class SourcePatch(CamelModel):
    mode: str | None = None
    anchor: str | None = None
    primary: bool | None = None


class SkeletonEntryOut(CamelModel):
    id: str
    kind: str
    label: str
