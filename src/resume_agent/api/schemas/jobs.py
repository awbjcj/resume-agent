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
    source: str
    location: str | None
    fit_score: int | None
    fit_rationale: str | None
    sponsorship_signal: str | None
    salary_min: float | None
    salary_max: float | None
    salary_currency: str | None
    remote_policy: str | None
    seniority: str | None
    employment_type: str | None
    industry: str | None
    company_size: str | None
    posted_at: datetime | None
    skills: list[SkillTagOut]
    location_country: str | None = None
    location_region: str | None = None
    location_city: str | None = None
    url: str | None = None


class PipelineItem(CamelModel):
    job_id: int
    company: str | None
    title: str | None
    source: str
    location: str | None
    status: str
    fit_score: int | None
    jd_text: str
    critique_json: list[dict] | None
    pdf_path: str | None
    application_status: str | None
    salary_min: float | None
    salary_max: float | None
    remote_policy: str | None
    seniority: str | None
    has_progress: bool
    needs_attention: bool = False
    regressed: bool = False
    url: str | None = None


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
    reject_reason: str | None = None
    url: str | None = None


class ResumeVersionOut(CamelModel):
    id: int
    job_id: int
    round: int
    origin: str = "tailor"
    instruction: str | None = None
    parent_version_id: int | None = None
    review_score: int | None
    fact_check_passed: bool
    pdf_path: str | None
    critique_json: list[dict] | None
    created_at: datetime


class CoverLetterOut(CamelModel):
    id: int
    job_id: int
    resume_version_id: int | None = None
    origin: str = "draft"
    instruction: str | None = None
    parent_id: int | None = None
    fact_check_passed: bool
    pdf_path: str | None
    created_at: datetime


class ApplicationOut(CamelModel):
    id: int
    job_id: int
    resume_version_id: int | None = None
    cover_letter_id: int | None = None
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
    cover_letters: list[CoverLetterOut] = []
    # Skill + meta facets (parsed from criteria_json server-side so the detail
    # modal renders the same covered/required channels as the board card).
    skills: list[SkillTagOut]
    sponsorship_signal: str | None = None
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str | None = None
    remote_policy: str | None = None
    seniority: str | None = None
    employment_type: str | None = None
    industry: str | None = None
    company_size: str | None = None
    location_country: str | None = None
    location_region: str | None = None
    location_city: str | None = None
    best_resume_version_id: int | None = None
    needs_attention: bool = False
    regressed: bool = False
    reject_reason: str | None = None


class JobPatch(CamelModel):
    status: str | None = None
    archived: bool | None = None


class ApplicationUpsert(CamelModel):
    status: str
    notes: str | None = None


class ReviseRequest(CamelModel):
    instruction: str
    re_review: bool = False


class JobsImportError(CamelModel):
    row: int
    reason: str


class JobsImportReportOut(CamelModel):
    added: int
    upgraded: int
    skipped: int
    errors: list[JobsImportError]


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
