"""Durable error-record response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from resume_agent.api.schemas.base import CamelModel


class ErrorRecordOut(CamelModel):
    id: int
    kind: str
    source_label: str
    run_id: str | None = None
    message: str = ""
    status: str
    count: int = 1
    first_seen_at: datetime
    last_seen_at: datetime
    updated_at: datetime


class ErrorRecordsOut(CamelModel):
    records: list[ErrorRecordOut] = Field(default_factory=list)


class DismissAllOut(CamelModel):
    dismissed: int = 0
