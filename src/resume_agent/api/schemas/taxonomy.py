"""Validated taxonomy edit request bodies."""

from __future__ import annotations

from pydantic import Field, field_validator

from resume_agent.api.schemas.base import CamelModel
from resume_agent.taxonomy.term_typing import (
    DecisionSource,
    TermConceptType,
    TermSourceKind,
)


class NewDomainIn(CamelModel):
    label: str = Field(min_length=1, max_length=80)
    category: str = Field(min_length=1, max_length=40)


class MoveSkillIn(CamelModel):
    domain_id: str | None = None
    new_domain: NewDomainIn | None = None


class AddSkillIn(CamelModel):
    token: str = Field(min_length=1, max_length=100)
    domain_id: str | None = None
    new_domain: NewDomainIn | None = None


class DomainPatchIn(CamelModel):
    label: str | None = Field(default=None, min_length=1, max_length=80)
    category: str | None = None


class DomainMergeIn(CamelModel):
    into: str = Field(min_length=1)


class AliasIn(CamelModel):
    token: str = Field(min_length=1, max_length=100)
    canonical: str = Field(min_length=1, max_length=100)


class TermSourceIn(CamelModel):
    source_kind: TermSourceKind
    source_id: str = Field(min_length=1, max_length=200)
    source_text: str | None = None
    original_text: str = Field(min_length=1, max_length=500)
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)

    @field_validator("source_kind", mode="before")
    @classmethod
    def normalize_source_kind(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        replacements = {
            "profileSkill": "profile_skill",
            "profileFact": "profile_fact",
            "jobDescription": "job_description",
            "jobCriteria": "job_criteria",
        }
        return replacements.get(value, value)


class TermTypeCorrectionIn(CamelModel):
    source: TermSourceIn
    new_type: TermConceptType
    rationale: str = Field(min_length=1, max_length=1000)
    evidence_refs: list[str] = Field(default_factory=list)


class TermSourceOut(CamelModel):
    source_kind: TermSourceKind
    source_id: str
    source_text: str | None = None
    original_text: str
    start: int | None = None
    end: int | None = None


class TermTypingDecisionOut(CamelModel):
    id: str
    source: TermSourceOut
    original_text: str
    normalized_text: str
    concept_type: TermConceptType
    concept_id: str | None = None
    confidence: float
    decision_source: DecisionSource
    reason_code: str
    policy_revision: str


class TermTypeCorrectionOut(CamelModel):
    id: str
    actor_id: str
    scope: str
    action: str
    subject_decision_id: str
    prior_type: TermConceptType
    new_type: TermConceptType
    rationale: str
    evidence_refs: list[str]
    target_revision: str
    timestamp: str
