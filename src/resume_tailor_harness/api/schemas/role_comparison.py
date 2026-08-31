"""Deterministic role-comparison API contracts."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, field_validator

from resume_tailor_harness.api.schemas.base import CamelModel
from resume_tailor_harness.company_intelligence.models import (
    CompanyResearchDepth,
    CompanyVerificationState,
)
from resume_tailor_harness.role_comparison.models import RoleComparisonItem


class RoleComparisonIn(CamelModel):
    job_ids: list[int] = Field(min_length=2, max_length=3)

    @field_validator("job_ids")
    @classmethod
    def distinct_positive_jobs(cls, value: list[int]) -> list[int]:
        if any(job_id <= 0 for job_id in value):
            raise ValueError("job ids must be positive")
        if len(set(value)) != len(value):
            raise ValueError("job ids must be distinct")
        return value


class CompanyEvidenceComparisonOut(CamelModel):
    state: str
    retrieved_at: datetime | None = None
    is_stale: bool | None = None
    research_depth: CompanyResearchDepth | None = None
    source_count: int | None = None
    strongest_verification: CompanyVerificationState | None = None


class RoleComparisonItemOut(CamelModel):
    job_id: int
    company: str | None = None
    title: str | None = None
    fit_score: int | None = None
    application_status: str
    company_evidence: CompanyEvidenceComparisonOut
    h1b_status: str | None = None
    offer_total: int | None = None
    offer_currency: str | None = None

    @classmethod
    def from_item(cls, item: RoleComparisonItem) -> RoleComparisonItemOut:
        return cls.model_validate(item.model_dump())


class RoleComparisonOut(CamelModel):
    items: list[RoleComparisonItemOut]
