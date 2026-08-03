"""Closed, persistence-safe models for the draft-only Career Lab."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from resume_agent.career_skills.models import (
    AgentRunMeta,
    CareerLabSkillName,
    SkillRef,
)
from resume_agent.models.base import ExtensibleModel
from resume_agent.sessions.store import SessionModel


class CareerLabArtifactRef(ExtensibleModel):
    session_id: str
    turn_id: str


class CareerLabContextRefs(ExtensibleModel):
    """Typed references projected into a prompt by the application layer."""

    profile_snapshot: Literal["current"] | None = None
    job_id: int | None = Field(default=None, ge=1)
    resume_version_id: int | None = Field(default=None, ge=1)
    offer_application_ids: list[int] = Field(
        default_factory=list, min_length=0, max_length=10
    )
    artifact: CareerLabArtifactRef | None = None

    @model_validator(mode="after")
    def _validate_ids(self) -> CareerLabContextRefs:
        if any(value < 1 for value in self.offer_application_ids):
            raise ValueError("offer application ids must be positive")
        return self


class CareerLabRoute(BaseModel):
    """Router output intentionally limited to the approved Career Lab enum."""

    model_config = ConfigDict(extra="forbid")

    skill: CareerLabSkillName | None = None
    needs_selection: bool = False
    reason: str = Field(default="", max_length=500)


class CareerLabArtifactMeta(ExtensibleModel):
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
    title: str = Field(max_length=200)
    summary: str = Field(max_length=1_000)


class CareerLabTurnRecord(ExtensibleModel):
    turn_id: str
    role: Literal["user", "assistant"]
    text: str = Field(max_length=100_000)
    at: str
    context_refs: CareerLabContextRefs | None = None
    skill_ref: SkillRef | None = None
    agent_meta: AgentRunMeta | None = None
    artifact: CareerLabArtifactMeta | None = None
    notice: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def _enforce_role_contract(self) -> CareerLabTurnRecord:
        if self.role == "user":
            if self.skill_ref is not None or self.agent_meta is not None:
                raise ValueError("user turns cannot carry agent provenance")
            if self.artifact is not None:
                raise ValueError("user turns cannot carry artifacts")
            return self

        if self.context_refs is not None:
            raise ValueError("assistant turns cannot carry context references")
        if self.skill_ref is None or self.agent_meta is None:
            raise ValueError("assistant turns require skill and agent metadata")
        if self.agent_meta.skill_ref != self.skill_ref:
            raise ValueError("assistant skill and agent metadata must match")
        return self


class CareerLabSession(SessionModel):
    title: str = Field(default="", max_length=120)
    goal: str = Field(default="", max_length=2_000)
    ended_at: str | None = None
    turns: list[CareerLabTurnRecord] = Field(default_factory=list)
