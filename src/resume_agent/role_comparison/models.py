"""Canonical role-comparison projections."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from resume_agent.company_intelligence.models import (
    CompanyResearchDepth,
    CompanyVerificationState,
)
from resume_agent.models.base import ExtensibleModel


class CompanyEvidenceComparison(ExtensibleModel):
    state: Literal["not_researched", "ready"]
    retrieved_at: datetime | None = None
    is_stale: bool | None = None
    research_depth: CompanyResearchDepth | None = None
    source_count: int | None = None
    strongest_verification: CompanyVerificationState | None = None


class RoleComparisonItem(ExtensibleModel):
    job_id: int
    company: str | None = None
    title: str | None = None
    fit_score: int | None = None
    application_status: str
    company_evidence: CompanyEvidenceComparison
    h1b_status: Literal["matched", "no_match", "unavailable"] | None = None
    offer_total: int | None = None
    offer_currency: str | None = None
