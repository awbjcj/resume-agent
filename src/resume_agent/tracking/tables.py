from datetime import datetime, timezone
from enum import Enum
from typing import Any, cast

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class JobStatus(str, Enum):
    """Our processing pipeline status for a job."""

    raw = "raw"
    extracted = "extracted"
    filtered = "filtered"
    rejected = "rejected"
    shortlisted = "shortlisted"
    approved = "approved"
    tailored = "tailored"
    rendered = "rendered"


class ApplicationStatus(str, Enum):
    """The employer-side funnel status for a submitted application."""

    ready = "ready"
    submitted = "submitted"
    interview = "interview"
    offer = "offer"
    rejected = "rejected"
    closed = "closed"


class Job(SQLModel, table=True):
    __tablename__ = cast(Any, "jobs")

    id: int | None = Field(default=None, primary_key=True)
    source: str
    url: str | None = Field(default=None, index=True)
    company: str | None = None
    title: str | None = None
    location: str | None = None
    dedup_key: str | None = Field(default=None, index=True)
    jd_text: str = ""
    criteria_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    analysis_meta_json: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON)
    )
    fit_score: int | None = None
    fit_rationale: str | None = None
    status: str = Field(default=JobStatus.raw.value, index=True)
    reject_reason: str | None = None
    reject_category: str | None = None
    gate_override: bool = Field(default=False)
    # Set when an extracted industry candidate could not be canonicalized, so
    # the next extract pass can find revisitable rows by index instead of
    # scanning every job's criteria JSON for a substring.
    industry_pending: bool = Field(default=False, index=True)
    content_fingerprint: str | None = Field(default=None, index=True)
    posted_at: datetime | None = None
    archived_at: datetime | None = Field(default=None, index=True)
    schema_version: int = 1
    created_at: datetime = Field(default_factory=utcnow)


class ResumeVersion(SQLModel, table=True):
    __tablename__ = cast(Any, "resume_versions")

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="jobs.id", index=True)
    round: int = 0
    content_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    pdf_path: str | None = None
    review_score: int | None = None
    fact_check_passed: bool = False
    critique_json: list[dict[str, Any]] | None = Field(
        default=None, sa_column=Column(JSON)
    )
    evidence_portfolio_json: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON)
    )
    evidence_portfolio_status: str | None = None
    skill_uses_json: list[dict[str, Any]] | None = Field(
        default=None, sa_column=Column(JSON)
    )
    # The configured gate reviewer names active for THIS round (provenance is
    # always a gate and is never included here). None means "unknown" - a row
    # written before this column existed - and read-side callers fall back to
    # the current review config for it; [] is a known, empty roster (no
    # reviewer-configured gates ran this round, only the deterministic ones).
    gate_reviewers_json: list[str] | None = Field(default=None, sa_column=Column(JSON))
    # None means "written before this column existed" - unknown, not empty.
    # A resume version records one attempt and is never backfilled: the taxonomy
    # that produced an older version cannot be reconstructed later.
    taxonomy_revision: str | None = None
    taxonomy_manifest_json: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON)
    )
    attempt: int = Field(default=0, index=True)
    tailor_model: str | None = None
    origin: str = Field(default="tailor", index=True)
    instruction: str | None = None
    parent_version_id: int | None = Field(
        default=None, foreign_key="resume_versions.id"
    )
    schema_version: int = 1
    created_at: datetime = Field(default_factory=utcnow)


class Application(SQLModel, table=True):
    __tablename__ = cast(Any, "applications")

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="jobs.id", index=True)
    resume_version_id: int | None = Field(
        default=None, foreign_key="resume_versions.id"
    )
    cover_letter_id: int | None = Field(default=None, foreign_key="cover_letters.id")
    status: str = Field(default=ApplicationStatus.ready.value, index=True)
    submitted_at: datetime | None = None
    notes: str | None = None
    updated_at: datetime = Field(
        default_factory=utcnow, sa_column_kwargs={"onupdate": utcnow}
    )


class ApplicationEvent(SQLModel, table=True):
    """One dated entry on an application's timeline.

    An event log rather than wide columns on Application: the round count is
    unbounded (loops run to five, companies insert team-match calls), so
    columns would cap the model and make every new stage a migration. The
    spreadsheet the user reads is a pivot over these rows.
    """

    __tablename__ = cast(Any, "application_events")

    id: int | None = Field(default=None, primary_key=True)
    application_id: int = Field(foreign_key="applications.id", index=True)

    kind: str = Field(index=True)
    custom_label: str | None = None
    sequence: int = 1
    # Explicit user choice, kept separately from the effective display order.
    # NULL means ``sequence`` is maintained chronologically by the service.
    sequence_override: int | None = None

    # UTC. `all_day` distinguishes "applied on the 3rd" from "Zoom at 14:00";
    # `timezone` is an IANA name, not an offset, because DST can shift between
    # logging an event and its occurrence.
    occurred_at: datetime | None = Field(default=None, index=True)
    all_day: bool = False
    timezone: str | None = None
    duration_minutes: int | None = None

    modality: str | None = None
    platform: str | None = None
    platform_other: str | None = None
    location_or_link: str | None = None
    interviewers: str | None = None

    result: str = Field(default="pending", index=True)
    notes: str | None = None
    reflection: str | None = None

    # offer_received only; total compensation is derived, never stored.
    comp_base: int | None = None
    comp_bonus: int | None = None
    comp_equity_annual: int | None = None
    comp_signing: int | None = None
    comp_currency: str | None = None

    source: str = Field(default="manual")  # manual | migration | gmail
    schema_version: int = 1
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class CoverLetter(SQLModel, table=True):
    __tablename__ = cast(Any, "cover_letters")

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="jobs.id", index=True)
    resume_version_id: int | None = Field(
        default=None, foreign_key="resume_versions.id"
    )
    content_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    skill_uses_json: list[dict[str, Any]] | None = Field(
        default=None, sa_column=Column(JSON)
    )
    pdf_path: str | None = None
    fact_check_passed: bool = False
    origin: str = Field(default="draft", index=True)
    instruction: str | None = None
    parent_id: int | None = Field(default=None, foreign_key="cover_letters.id")
    schema_version: int = 1
    created_at: datetime = Field(default_factory=utcnow)


class Notification(SQLModel, table=True):
    __tablename__ = cast(Any, "notifications")

    id: int | None = Field(default=None, primary_key=True)
    application_id: int = Field(foreign_key="applications.id", index=True)
    kind: str
    proposed_status: str
    evidence: str
    message_id: str = Field(index=True)
    state: str = Field(default="pending", index=True)
    created_at: datetime = Field(default_factory=utcnow)


class SavedBoardView(SQLModel, table=True):
    """A named snapshot of one board's canonical URL filter state."""

    __tablename__ = cast(Any, "saved_board_views")
    __table_args__ = (
        UniqueConstraint("board", "name", name="uq_saved_board_view_board_name"),
    )

    id: int | None = Field(default=None, primary_key=True)
    board: str = Field(index=True)
    name: str
    query_string: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(
        default_factory=utcnow, sa_column_kwargs={"onupdate": utcnow}
    )


class RunCompletion(SQLModel, table=True):
    """Durable terminal run history, independent of short-lived run JSON."""

    __tablename__ = cast(Any, "run_completions")
    __table_args__ = (UniqueConstraint("run_id", name="uq_run_completion_run_id"),)

    id: int | None = Field(default=None, primary_key=True)
    run_id: str = Field(index=True)
    kind: str = Field(index=True)
    label: str = ""
    status: str = Field(index=True)
    error: str | None = None
    completed_at: datetime = Field(index=True)
    read_at: datetime | None = Field(default=None, index=True)


class EmailDraft(SQLModel, table=True):
    __tablename__ = cast(Any, "email_drafts")

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="jobs.id", index=True)
    draft_type: str  # follow_up | thank_you | withdrawal | cold_outreach
    subject: str
    body: str
    to_addr: str = ""
    gmail_thread_id: str | None = None
    gmail_draft_id: str | None = None
    state: str = Field(default="generated")  # generated | saved
    created_at: datetime = Field(default_factory=utcnow)


class SkillSuggestion(SQLModel, table=True):
    __tablename__ = cast(Any, "skill_suggestions")
    __table_args__ = (
        UniqueConstraint("kind", "key", name="uq_skill_suggestion_kind_key"),
    )

    id: int | None = Field(default=None, primary_key=True)
    kind: str = Field(index=True)
    key: str = Field(index=True)
    payload_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    fingerprint: str = ""
    generated_at: datetime = Field(default_factory=utcnow)
    schema_version: int = 1


class H1BCompanyEvidence(SQLModel, table=True):
    __tablename__ = cast(Any, "h1b_company_evidence")
    __table_args__ = (UniqueConstraint("normalized_company"),)

    id: int | None = Field(default=None, primary_key=True)
    normalized_company: str = Field(index=True)
    display_company: str | None = None
    status: str = Field(index=True)
    evidence_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    source_url: str | None = None
    data_version: str | None = None
    retrieved_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime = Field(index=True)
    schema_version: int = 1


class CompanyIntelligenceEvidenceRow(SQLModel, table=True):
    __tablename__ = cast(Any, "company_intelligence_evidence")
    __table_args__ = (UniqueConstraint("normalized_company"),)

    id: int | None = Field(default=None, primary_key=True)
    normalized_company: str = Field(index=True)
    display_company: str = ""
    evidence_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    retrieved_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime = Field(index=True)
    schema_version: int = 1


class CompanyIntelligenceVersionRow(SQLModel, table=True):
    """One immutable observation created by an explicit company refresh."""

    __tablename__ = cast(Any, "company_intelligence_versions")
    __table_args__ = (
        UniqueConstraint(
            "normalized_company",
            "version_number",
            name="uq_company_intelligence_version",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    normalized_company: str = Field(index=True)
    display_company: str = ""
    version_number: int = Field(index=True)
    previous_version_id: int | None = Field(
        default=None, foreign_key="company_intelligence_versions.id"
    )
    research_depth: str = "standard"
    evidence_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    change_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False),
    )
    retrieved_at: datetime = Field(default_factory=utcnow, index=True)
    expires_at: datetime = Field(index=True)
    schema_version: int = 2


class ErrorRecord(SQLModel, table=True):
    """A durable failure record that the user can dismiss or resolve."""

    __tablename__ = cast(Any, "error_records")

    id: int | None = Field(default=None, primary_key=True)
    kind: str = Field(index=True)
    source_label: str = Field(index=True)
    run_id: str | None = None
    message: str = ""
    details_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    status: str = Field(default="open", index=True)
    count: int = 1
    first_seen_at: datetime = Field(default_factory=utcnow)
    last_seen_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
