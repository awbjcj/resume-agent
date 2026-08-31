"""Request/response models for board bulk actions."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from resume_tailor_harness.api.schemas.base import CamelModel
from resume_tailor_harness.tracking.board_query import Preset, SortKey


class BulkRequest(CamelModel):
    board: Literal["shortlist", "triage", "pipeline"]
    action: Literal["archive", "restore", "delete", "approve", "setStatus"]
    scope: Literal["ids", "query"]
    ids: list[int] = Field(default_factory=list)
    status: str | None = None
    dry_run: bool = True
    archived: bool = False
    q: str | None = None
    reject_reason: str | None = None
    source: list[str] = Field(default_factory=list)
    status_in: list[str] = Field(default_factory=list)
    remote: list[str] = Field(default_factory=list)
    sponsorship: list[str] = Field(default_factory=list)
    seniority: list[str] = Field(default_factory=list)
    employment_type: list[str] = Field(default_factory=list)
    industry: list[str] = Field(default_factory=list)
    country: list[str] = Field(default_factory=list)
    region: list[str] = Field(default_factory=list)
    city: list[str] = Field(default_factory=list)
    company_size: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    min_fit: int | None = None
    max_fit: int | None = None
    min_salary: int | None = None
    stale_days: int | None = None
    stale_min_days: int | None = None
    sort_by: SortKey = "fit"
    preset: Preset = "balanced"


class BulkResultOut(CamelModel):
    affected: int
    skipped: int
    reasons: dict[str, int]
