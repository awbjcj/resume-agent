"""Job-scoped role-preparation API contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from resume_agent.api.schemas.base import CamelModel
from resume_agent.role_preparation.models import RolePreparationBrief, RoleQuestionType


class RolePreparationCompetencyOut(CamelModel):
    name: str
    rationale: str
    company_citations: list[str] = Field(default_factory=list)


class RolePreparationQuestionOut(CamelModel):
    question: str
    question_type: RoleQuestionType
    competency: str
    rationale: str
    company_citations: list[str] = Field(default_factory=list)
    story_prompt: str


class RolePreparationConcernOut(CamelModel):
    concern: str
    preparation: str
    company_citations: list[str] = Field(default_factory=list)


class RolePreparationAskOut(CamelModel):
    text: str
    rationale: str
    company_citations: list[str] = Field(default_factory=list)


class RolePreparationBriefOut(CamelModel):
    job_id: int
    company: str
    title: str
    generated_at: datetime
    input_fingerprint: str
    company_intelligence_version_id: int | None = None
    company_intelligence_version_number: int = 1
    resume_version_id: int | None = None
    cover_letter_id: int | None = None
    application_status: str
    signal_event_ids: list[int] = Field(default_factory=list)
    positioning_summary: str
    competencies: list[RolePreparationCompetencyOut] = Field(default_factory=list)
    likely_questions: list[RolePreparationQuestionOut] = Field(default_factory=list)
    concerns: list[RolePreparationConcernOut] = Field(default_factory=list)
    questions_to_ask: list[RolePreparationAskOut] = Field(default_factory=list)
    recruiter_verification_questions: list[RolePreparationAskOut] = Field(
        default_factory=list
    )
    prior_round_focus: list[str] = Field(default_factory=list)
    caveat: str

    @classmethod
    def from_brief(cls, brief: RolePreparationBrief) -> RolePreparationBriefOut:
        return cls.model_validate(brief.model_dump())


class RolePreparationBaseOut(CamelModel):
    message: str | None = None


class RolePreparationUnavailableOut(RolePreparationBaseOut):
    state: Literal["unavailable"] = "unavailable"
    reason: Literal[
        "missing_job_description", "company_intelligence_required"
    ]
    can_refresh: Literal[False] = False
    inputs_changed: Literal[False] = False
    brief: None = None


class RolePreparationEmptyOut(RolePreparationBaseOut):
    state: Literal["empty"] = "empty"
    reason: Literal["not_generated"] = "not_generated"
    can_refresh: Literal[True] = True
    inputs_changed: Literal[False] = False
    brief: None = None


class RolePreparationReadyOut(RolePreparationBaseOut):
    state: Literal["ready"] = "ready"
    reason: None = None
    can_refresh: Literal[True] = True
    inputs_changed: bool = False
    brief: RolePreparationBriefOut


RolePreparationOut = Annotated[
    RolePreparationUnavailableOut
    | RolePreparationEmptyOut
    | RolePreparationReadyOut,
    Field(discriminator="state"),
]
