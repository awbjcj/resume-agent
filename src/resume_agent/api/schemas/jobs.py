"""Job-side API schemas: board items, detail, patch, sub-resources, prune."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from resume_agent.api.schemas.base import CamelModel
from resume_agent.company_intelligence.models import (
    CompanyIntelligenceAxis,
    CompanyIntelligenceEvidence,
    CompanySourceType,
)
from resume_agent.h1b.models import H1BSponsorshipEvidence
from resume_agent.models.review import ReviewCritique
from resume_agent.tailor.verdict import failing_gate_names


H1BSponsorshipStatus = Literal["matched", "no_match", "unavailable"]


class SkillTagOut(CamelModel):
    name: str
    covered: bool
    required: bool


class LocationInstanceOut(CamelModel):
    """One canonical work-location alternative for a job posting."""

    city: str | None = None
    region: str | None = None
    country: str | None = None
    is_us: bool = False
    raw: str | None = None


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
    locations: list[LocationInstanceOut] = Field(default_factory=list)
    location_country: str | None = None
    location_region: str | None = None
    location_city: str | None = None
    url: str | None = None
    h1b_sponsorship_status: H1BSponsorshipStatus | None = None


class PipelineItem(CamelModel):
    job_id: int
    company: str | None
    title: str | None
    source: str
    location: str | None
    status: str
    fit_score: int | None
    jd_preview: str
    critique_json: list[dict] | None
    pdf_path: str | None
    application_status: str | None
    salary_min: float | None
    salary_max: float | None
    salary_currency: str | None = None
    remote_policy: str | None
    seniority: str | None
    sponsorship_signal: str | None = None
    employment_type: str | None = None
    industry: str | None = None
    company_size: str | None = None
    posted_at: datetime | None = None
    locations: list[LocationInstanceOut] = Field(default_factory=list)
    location_country: str | None = None
    location_region: str | None = None
    location_city: str | None = None
    reject_reason: str | None = None
    reject_category: str | None = None
    has_progress: bool
    needs_attention: bool = False
    regressed: bool = False
    url: str | None = None
    h1b_sponsorship_status: H1BSponsorshipStatus | None = None


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
    locations: list[LocationInstanceOut] = Field(default_factory=list)
    reject_reason: str | None = None
    reject_category: str | None = None
    url: str | None = None
    h1b_sponsorship_status: H1BSponsorshipStatus | None = None


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
    failed_gates: list[str] = Field(default_factory=list)
    evidence_portfolio_status: str | None = None
    has_evidence_portfolio: bool = False
    # Stored provenance is not exposed directly, but drives the public signal
    # that a legacy version predates taxonomy revision recording.
    taxonomy_revision: str | None = Field(default=None, exclude=True)
    revision_unknown: bool = True
    # The round's OWN recorded gate roster (`ResumeVersion.gate_reviewers_json`).
    # None means a row written before this field existed - unknown, not empty -
    # and `apply_gate_names` treats that as the signal to fall back to a
    # caller-supplied roster. Never serialized: it exists only to drive
    # `failed_gates`, not as a UI-facing field.
    gate_reviewers_json: list[str] | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def _default_failed_gates(self) -> ResumeVersionOut:
        """Which gates blocked this round, so the UI can name the real cause.

        `fact_check_passed` is the AND of provenance and fact-check, so it alone
        rendered "Fact-check failed" on rounds where fact-check never ran. Uses
        this round's own recorded gate roster when present; falls back to the
        shipped fixed roster (`fact-check`) only for rows persisted before
        `gate_reviewers_json` existed, pending a caller-supplied override via
        `apply_gate_names`.
        """
        self.failed_gates = failing_gate_names(
            [ReviewCritique.model_validate(c) for c in self.critique_json or []],
            self.gate_reviewers_json,
        )
        self.has_evidence_portfolio = self.evidence_portfolio_status is not None
        self.revision_unknown = self.taxonomy_revision is None
        return self

    def apply_gate_names(self, gate_names: Iterable[str]) -> None:
        """Recompute `failed_gates` against a fallback gate roster.

        A no-op when this version already recorded its own gates
        (`gate_reviewers_json is not None`) - overriding it with the CURRENT
        review config would relabel history whenever settings change after the
        round ran. Only legacy rows without a recorded roster fall back to
        `gate_names`.
        """
        if self.gate_reviewers_json is not None:
            return
        self.failed_gates = failing_gate_names(
            [ReviewCritique.model_validate(c) for c in self.critique_json or []],
            gate_names,
        )


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


class ArtifactDeleteRequest(CamelModel):
    # At least one id: an empty batch is a client bug, not a no-op delete.
    ids: list[int] = Field(min_length=1)


class ArtifactDeleteOut(CamelModel):
    deleted: int


class H1BPeriodStatOut(CamelModel):
    period: str
    filing_count: int | None = None
    certified_count: int | None = None
    denied_count: int | None = None
    wage_summary: dict[str, float] | None = None


class H1BSponsorshipEvidenceOut(CamelModel):
    status: H1BSponsorshipStatus
    normalized_company: str
    display_company: str | None
    fiscal_periods: list[str]
    filing_count: int | None
    certified_count: int | None
    denied_count: int | None = None
    periods: list[H1BPeriodStatOut] = Field(default_factory=list)
    wage_summary: dict[str, float] | None
    source_url: str | None
    data_version: str | None
    retrieved_at: datetime
    expires_at: datetime
    confidence: float
    caveat: str
    unavailable_reason: str | None = None

    @classmethod
    def from_evidence(
        cls, evidence: H1BSponsorshipEvidence
    ) -> H1BSponsorshipEvidenceOut:
        return cls.model_validate(evidence.model_dump())


class H1BSponsorshipOut(CamelModel):
    capability: Literal["disabled", "available", "unavailable"]
    stale: bool = False
    evidence: H1BSponsorshipEvidenceOut | None = None
    message: str | None = None


class CompanyIntelligenceSourceOut(CamelModel):
    title: str
    url: str
    publisher: str
    source_type: CompanySourceType


class CompanyIntelligenceInsightOut(CamelModel):
    axis: CompanyIntelligenceAxis
    summary: str
    why_it_matters: str
    citations: list[str] = Field(default_factory=list)


class CompanyIntelligenceEvidenceOut(CamelModel):
    normalized_company: str
    display_company: str
    overview: str
    insights: list[CompanyIntelligenceInsightOut] = Field(default_factory=list)
    sources: list[CompanyIntelligenceSourceOut] = Field(default_factory=list)
    retrieved_at: datetime
    expires_at: datetime
    caveat: str

    @classmethod
    def from_evidence(
        cls, evidence: CompanyIntelligenceEvidence
    ) -> CompanyIntelligenceEvidenceOut:
        return cls.model_validate(evidence.model_dump())


class CompanyIntelligenceBaseOut(CamelModel):
    """Fields shared by every company-intelligence resource state."""

    message: str | None = None


class CompanyIntelligenceUnavailableOut(CompanyIntelligenceBaseOut):
    state: Literal["unavailable"] = "unavailable"
    reason: Literal["missing_company"] = "missing_company"
    capability: Literal["unavailable"] = Field(default="unavailable", deprecated=True)
    stale: Literal[False] = Field(default=False, deprecated=True)
    is_stale: Literal[False] = False
    can_refresh: Literal[False] = False
    evidence: None = None


class CompanyIntelligenceEmptyOut(CompanyIntelligenceBaseOut):
    state: Literal["empty"] = "empty"
    reason: Literal["not_researched"] = "not_researched"
    capability: Literal["unavailable"] = Field(default="unavailable", deprecated=True)
    stale: Literal[False] = Field(default=False, deprecated=True)
    is_stale: Literal[False] = False
    can_refresh: Literal[True] = True
    evidence: None = None


class CompanyIntelligenceReadyOut(CompanyIntelligenceBaseOut):
    state: Literal["ready"] = "ready"
    reason: None = None
    capability: Literal["available"] = Field(default="available", deprecated=True)
    stale: bool = Field(default=False, deprecated=True)
    is_stale: bool = False
    can_refresh: Literal[True] = True
    evidence: CompanyIntelligenceEvidenceOut


CompanyIntelligenceOut = Annotated[
    CompanyIntelligenceUnavailableOut
    | CompanyIntelligenceEmptyOut
    | CompanyIntelligenceReadyOut,
    Field(discriminator="state"),
]


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
    locations: list[LocationInstanceOut] = Field(default_factory=list)
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
    reject_category: str | None = None
    h1b_sponsorship: H1BSponsorshipOut | None = None
    company_intelligence: CompanyIntelligenceOut


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
