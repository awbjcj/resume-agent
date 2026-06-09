from datetime import datetime, timezone
from enum import Enum
from typing import Any

from sqlalchemy import JSON, Column
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
    __tablename__ = "jobs"

    id: int | None = Field(default=None, primary_key=True)
    source: str
    url: str | None = None
    company: str | None = None
    title: str | None = None
    location: str | None = None
    jd_text: str = ""
    criteria_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    fit_score: int | None = None
    fit_rationale: str | None = None
    status: str = Field(default=JobStatus.raw.value, index=True)
    reject_reason: str | None = None
    schema_version: int = 1
    created_at: datetime = Field(default_factory=utcnow)


class ResumeVersion(SQLModel, table=True):
    __tablename__ = "resume_versions"

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="jobs.id", index=True)
    round: int = 0
    content_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    pdf_path: str | None = None
    review_score: int | None = None
    fact_check_passed: bool = False
    critique_json: list[dict[str, Any]] | None = Field(default=None, sa_column=Column(JSON))
    schema_version: int = 1
    created_at: datetime = Field(default_factory=utcnow)


class Application(SQLModel, table=True):
    __tablename__ = "applications"

    id: int | None = Field(default=None, primary_key=True)
    job_id: int = Field(foreign_key="jobs.id", index=True)
    resume_version_id: int | None = Field(default=None, foreign_key="resume_versions.id")
    status: str = Field(default=ApplicationStatus.ready.value, index=True)
    submitted_at: datetime | None = None
    notes: str | None = None
    updated_at: datetime = Field(default_factory=utcnow)
