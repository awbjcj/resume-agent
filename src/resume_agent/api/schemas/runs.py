# src/resume_agent/api/schemas/runs.py  (partial — completed in Task 12)
from __future__ import annotations

from resume_agent.api.schemas.base import CamelModel


class AddJobTextRequest(CamelModel):
    jd_text: str
    url: str | None = None
    company: str | None = None
    title: str | None = None
    location: str | None = None
