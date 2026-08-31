"""Typed role-preparation artifacts and their frozen generation inputs."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from resume_tailor_harness.models.base import ExtensibleModel

RoleQuestionType = Literal[
    "screening",
    "behavioral",
    "technical",
    "system_design",
    "case",
    "company",
    "other",
]


class RolePreparationCompetency(ExtensibleModel):
    name: str = ""
    rationale: str = ""
    company_citations: list[str] = Field(default_factory=list)


class RolePreparationQuestion(ExtensibleModel):
    question: str = ""
    question_type: RoleQuestionType = "other"
    competency: str = ""
    rationale: str = ""
    company_citations: list[str] = Field(default_factory=list)
    story_prompt: str = ""


class RolePreparationConcern(ExtensibleModel):
    concern: str = ""
    preparation: str = ""
    company_citations: list[str] = Field(default_factory=list)


class RolePreparationAsk(ExtensibleModel):
    text: str = ""
    rationale: str = ""
    company_citations: list[str] = Field(default_factory=list)


class RolePreparationDraft(ExtensibleModel):
    positioning_summary: str = ""
    competencies: list[RolePreparationCompetency] = Field(default_factory=list)
    likely_questions: list[RolePreparationQuestion] = Field(default_factory=list)
    concerns: list[RolePreparationConcern] = Field(default_factory=list)
    questions_to_ask: list[RolePreparationAsk] = Field(default_factory=list)
    recruiter_verification_questions: list[RolePreparationAsk] = Field(
        default_factory=list
    )
    prior_round_focus: list[str] = Field(default_factory=list)


class RolePreparationInputs(ExtensibleModel):
    job_id: int
    company: str = ""
    title: str = ""
    jd_text: str = ""
    company_intelligence: dict = Field(default_factory=dict)
    company_intelligence_version_id: int | None = None
    company_intelligence_version_number: int = 1
    resume_version_id: int | None = None
    resume_content: dict = Field(default_factory=dict)
    cover_letter_id: int | None = None
    cover_letter_content: dict = Field(default_factory=dict)
    application_status: str = "ready"
    interview_signals: list[dict] = Field(default_factory=list)
    signal_event_ids: list[int] = Field(default_factory=list)


class RolePreparationBrief(RolePreparationDraft):
    schema_version: int = 1
    job_id: int
    company: str = ""
    title: str = ""
    generated_at: datetime
    input_fingerprint: str
    company_intelligence_version_id: int | None = None
    company_intelligence_version_number: int = 1
    resume_version_id: int | None = None
    cover_letter_id: int | None = None
    application_status: str = "ready"
    signal_event_ids: list[int] = Field(default_factory=list)
    caveat: str
