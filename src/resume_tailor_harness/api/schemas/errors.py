"""Durable error-record response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from resume_tailor_harness.api.schemas.base import CamelModel, Pagination
from resume_tailor_harness.services.redo import RedoStage


class JobFailureDetails(CamelModel):
    """The formatted diagnostic for one job's stage failure.

    Typed rather than a free-form map: an exposed dict's keys become a de facto
    contract with nothing holding them stable, and a schema flows into the
    generated TS client so the web side needs no hand-written shape.
    """

    job_id: int
    stage: RedoStage
    error_type: str
    message: str
    company: str | None = None
    title: str | None = None
    model: str | None = None
    traceback_tail: str = ""


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
    job_details: JobFailureDetails | None = None


class ErrorRecordsOut(CamelModel):
    records: list[ErrorRecordOut] = Field(default_factory=list)
    pagination: Pagination | None = None


class DismissAllOut(CamelModel):
    dismissed: int = 0
