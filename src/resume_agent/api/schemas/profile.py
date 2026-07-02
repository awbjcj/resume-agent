"""Profile document + build wire schemas."""

from __future__ import annotations

from resume_agent.api.schemas.base import CamelModel


class DocumentOut(CamelModel):
    id: str
    filename: str
    doc_type: str
    size_bytes: int
    uploaded_at: str
