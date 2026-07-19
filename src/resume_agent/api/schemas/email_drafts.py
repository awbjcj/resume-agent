from __future__ import annotations

from datetime import datetime

from resume_agent.api.schemas.base import CamelModel


class EmailDraftRequest(CamelModel):
    draft_type: str
    instructions: str | None = None


class EmailDraftOut(CamelModel):
    id: int
    job_id: int
    draft_type: str
    subject: str
    body: str
    to_addr: str
    gmail_thread_id: str | None = None
    gmail_draft_id: str | None = None
    state: str
    created_at: datetime
