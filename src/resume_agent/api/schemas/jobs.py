"""Job-side API schemas: board items, detail, patch, sub-resources, prune."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from resume_agent.api.schemas.base import CamelModel


class SkillTagOut(CamelModel):
    name: str
    covered: bool
    required: bool


class ShortlistItem(CamelModel):
    job_id: int
    company: str | None
    title: str | None
    location: str | None
    fit_score: int | None
    fit_rationale: str | None
    sponsorship_signal: str | None
    salary_min: int | None
    salary_max: int | None
    salary_currency: str | None
    remote_policy: str | None
    seniority: str | None
    employment_type: str | None
    industry: str | None
    company_size: str | None
    posted_at: datetime | None
    skills: list[SkillTagOut]
    sic_major: str | None = None
    sic_label: str | None = None
    sic_division: str | None = None
    location_country: str | None = None
    location_region: str | None = None
    location_city: str | None = None


class PipelineItem(CamelModel):
    job_id: int
    company: str | None
    title: str | None
    status: str
    fit_score: int | None
    jd_text: str
    critique_json: list[dict] | None
    pdf_path: str | None
    application_status: str | None
    salary_min: int | None
    salary_max: int | None
    remote_policy: str | None
    seniority: str | None
    has_progress: bool


class TriageItem(CamelModel):
    job_id: int
    company: str | None
    title: str | None
    location: str | None
    source: str
    status: str
    fit_score: int | None
    posted_at: datetime | None
    archived_at: datetime | None
    has_progress: bool


class ResumeVersionOut(CamelModel):
    id: int
    job_id: int
    round: int
    review_score: int | None
    fact_check_passed: bool
    pdf_path: str | None
    critique_json: list[dict] | None
    created_at: datetime


class ApplicationOut(CamelModel):
    id: int
    job_id: int
    status: str
    notes: str | None
    submitted_at: datetime | None
    updated_at: datetime


class JobDetail(CamelModel):
    id: int
    source: str
    url: str | None
    company: str | None
    title: str | None
    location: str | None
    jd_text: str
    status: str
    fit_score: int | None
    fit_rationale: str | None
    criteria_json: dict[str, Any] | None
    posted_at: datetime | None
    archived_at: datetime | None
    created_at: datetime
    has_progress: bool
    application: ApplicationOut | None
    resume_versions: list[ResumeVersionOut]


class JobPatch(CamelModel):
    status: str | None = None
    archived: bool | None = None


class ApplicationUpsert(CamelModel):
    status: str
    notes: str | None = None


class PruneOverrides(CamelModel):
    dry_run: bool = True
    fit_threshold: int | None = None
    stale_days: int | None = None
    retention_days: int | None = None


class PruneReportOut(CamelModel):
    archived: int
    expired: int
    skipped: int
    rejected: int
    low_fit: int
    stale: int
