from __future__ import annotations

from datetime import datetime
from typing import Literal

from resume_agent.api.schemas.base import CamelModel


class RunCompletionOut(CamelModel):
    id: int
    run_id: str
    kind: str
    label: str
    status: Literal["succeeded", "failed", "cancelled"]
    error: str | None = None
    completed_at: datetime
    read_at: datetime | None = None


class RunCompletionsReadOut(CamelModel):
    marked_read: int
