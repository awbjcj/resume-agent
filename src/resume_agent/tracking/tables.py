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
    url: str | None = None
    company: str | None = None
    title: str | None = None
    location: str | None = None
    dedup_key: str | None = Field(default=None, index=True)
    jd_text: str = ""
    criteria_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    fit_score: int | None = None
    fit_rationale: str | None = None
    status: str = Field(default=JobStatus.raw.value, index=True)
    reject_reason: str | None = None
    reject_category: str | None = None
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
    critique_json: list[dict[str, Any]] | None = Field(default=None, sa_column=Column(JSON))
    origin: str = Field(default="tailor", index=True)
    instruction: str | None = None
    parent_version_id: int | None = Field(default=None, foreign_key="resume_versions.id")
    schema_version: int = 1
    created_at: datetime = Field(default_factory=utcnow)


class Application(SQLModel, table=True):
    __tablename__ = cast(Any, "applications")

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="jobs.id", index=True)
    resume_version_id: int | None = Field(default=None, foreign_key="resume_versions.id")
    cover_letter_id: int | None = Field(default=None, foreign_key="cover_letters.id")
    status: str = Field(default=ApplicationStatus.ready.value, index=True)
    submitted_at: datetime | None = None
    notes: str | None = None
    updated_at: datetime = Field(
        default_factory=utcnow, sa_column_kwargs={"onupdate": utcnow}
    )


class CoverLetter(SQLModel, table=True):
    __tablename__ = cast(Any, "cover_letters")

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="jobs.id", index=True)
    resume_version_id: int | None = Field(default=None, foreign_key="resume_versions.id")
    content_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
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
