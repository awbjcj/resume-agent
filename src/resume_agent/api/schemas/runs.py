"""Run launch/status schemas + the manual-add request body."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator

from resume_agent.career_skills.models import CoverLetterSkillName, ResumeAuthoringSkillName
from resume_agent.api.runs.models import RunState
from resume_agent.api.schemas.base import CamelModel
from resume_agent.services.redo import RedoStage


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
    error_code: str | None = None
    meta: dict[str, Any] | None = None


class PullParams(CamelModel):
    limit: int | None = None
    source_ids: list[str] | None = None
    refresh: bool | None = None


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
    deep: bool = False
    authoring_skill: ResumeAuthoringSkillName | None = None


class CoverLetterParams(CamelModel):
    job_ids: list[int] | None = None
    approved: bool = False
    skill: CoverLetterSkillName | None = None


class AddJobUrlParams(CamelModel):
    url: str
    company: str | None = None
    title: str | None = None
    location: str | None = None
    allow_browser: bool = True


def _dedupe(values: list) -> list:
    """Order-preserving dedupe."""
    return list(dict.fromkeys(values))


class RedoParams(CamelModel):
    """Which jobs to redo and which stages to run.

    Validated here and nowhere deeper: redo_jobs trusts its inputs. Deduping
    stages matters because ["tailor", "tailor"] would otherwise bill twice.
    """

    job_ids: list[int] = Field(min_length=1)
    stages: list[RedoStage] = Field(min_length=1)
    deep: bool = False

    @field_validator("job_ids", "stages")
    @classmethod
    def _drop_duplicates(cls, value: list) -> list:
        return _dedupe(value)


class StageOutcomeOut(CamelModel):
    job_id: int
    stage: RedoStage
    status: Literal["ok", "skipped", "failed"]
    detail: str | None = None


class RedoResultOut(CamelModel):
    outcomes: list[StageOutcomeOut] = Field(default_factory=list)
