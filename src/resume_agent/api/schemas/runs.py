"""Run launch/status schemas + the manual-add request body."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from resume_agent.api.runs.models import RunState
from resume_agent.api.schemas.base import CamelModel


class AddJobTextRequest(CamelModel):
    jd_text: str
    url: str | None = None
    company: str | None = None
    title: str | None = None
    location: str | None = None


class RunOut(CamelModel):
    run_id: str
    kind: str
    state: RunState
    label: str
    percent: int
    current: int
    total: int
    eta_text: str | None = None
    result: Any | None = None
    error: str | None = None


class PullParams(CamelModel):
    limit: int | None = None
    source_ids: list[str] | None = None


class DiscoverParams(CamelModel):
    # Discover now only runs the funnel over new (raw) jobs. No modes.
    pass


class ReprocessParams(CamelModel):
    scopes: list[str] = Field(default_factory=lambda: ["shortlisted"])


class RefreshParams(CamelModel):
    limit: int | None = None


class TailorParams(CamelModel):
    job_ids: list[int] | None = None
    approved: bool = False


class CoverLetterParams(CamelModel):
    job_ids: list[int] | None = None
    approved: bool = False


class AddJobUrlParams(CamelModel):
    url: str
    company: str | None = None
    title: str | None = None
    location: str | None = None
    allow_browser: bool = True
