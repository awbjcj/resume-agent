from __future__ import annotations

from datetime import datetime

from resume_agent.api.schemas.base import CamelModel


class NotificationOut(CamelModel):
    id: int
    application_id: int
    kind: str
    proposed_status: str
    evidence: str
    message_id: str
    state: str
    created_at: datetime
