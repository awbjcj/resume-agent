"""CamelCase REST contracts for the draft-only Career Lab."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from resume_agent.api.schemas.base import CamelModel, Pagination
from resume_agent.career_skills.models import CareerLabSkillName


class CareerLabArtifactRefIn(CamelModel):
    session_id: str
    turn_id: str


class CareerLabContextIn(CamelModel):
    profile_snapshot: Literal["current"] | None = None
    job_id: int | None = Field(default=None, ge=1)
    resume_version_id: int | None = Field(default=None, ge=1)
    offer_application_ids: list[int] = Field(
        default_factory=list, min_length=0, max_length=10
    )
    artifact: CareerLabArtifactRefIn | None = None

    @field_validator("offer_application_ids")
    @classmethod
    def require_positive_offer_ids(cls, value: list[int]) -> list[int]:
        if any(item < 1 for item in value):
            raise ValueError("offer application ids must be positive")
        return value


class CareerLabStartIn(CamelModel):
    message: str = Field(min_length=1, max_length=100_000)
    goal: str = Field(default="", max_length=2_000)
    skill: CareerLabSkillName | None = None
    context: CareerLabContextIn | None = None


class CareerLabMessageIn(CamelModel):
    message: str = Field(min_length=1, max_length=100_000)
    skill: CareerLabSkillName | None = None
    context: CareerLabContextIn | None = None


class CareerLabSkillOut(CamelModel):
    name: str
    description: str = ""
    family: str
    uses: list[str] = Field(default_factory=list)
    is_available: bool
    unavailable_reason: str | None = None


class CareerLabSkillsOut(CamelModel):
    skills: list[CareerLabSkillOut] = Field(default_factory=list)


class CareerLabSkillRefOut(CamelModel):
    name: str
    version: str
    sha256: str
    family: str


class CareerLabAgentMetaOut(CamelModel):
    agent_family: str
    prompt_policy_version: str
    model_id: str
    skill_ref: CareerLabSkillRefOut | None = None


class CareerLabArtifactOut(CamelModel):
    artifact_type: Literal[
        "application_answer",
        "email",
        "linkedin_profile",
        "offer_comparison",
        "case_study",
        "reference_list",
        "career_plan",
        "negotiation_plan",
    ]
    title: str
    summary: str


class CareerLabTurnOut(CamelModel):
    turn_id: str
    role: Literal["user", "assistant"]
    text: str
    at: str
    context_refs: CareerLabContextIn | None = None
    skill_ref: CareerLabSkillRefOut | None = None
    agent_meta: CareerLabAgentMetaOut | None = None
    artifact: CareerLabArtifactOut | None = None
    notice: str = ""


class CareerLabSessionOut(CamelModel):
    session_id: str
    goal: str = ""
    started_at: str
    ended_at: str | None = None
    status: Literal["active", "ended"]
    archived_at: str | None = None
    turns: list[CareerLabTurnOut] = Field(default_factory=list)


class CareerLabSessionSummaryOut(CamelModel):
    session_id: str
    goal: str = ""
    started_at: str
    ended_at: str | None = None
    status: Literal["active", "ended"]
    archived_at: str | None = None
    turn_count: int = 0


class CareerLabSessionsOut(CamelModel):
    sessions: list[CareerLabSessionSummaryOut] = Field(default_factory=list)
    pagination: Pagination
