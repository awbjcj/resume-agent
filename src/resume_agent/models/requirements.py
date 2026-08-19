"""Source-grounded UCCM job requirement records."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from resume_agent.models.base import ExtensibleModel
from resume_agent.profile.assertions import ProficiencyLevel
from resume_agent.taxonomy.term_typing import TermConceptType

JOB_EXTRACTION_POLICY_REVISION = "job-requirements-v1"

RequirementKind = Literal[
    "must_have",
    "preferred",
    "responsibility",
    "context",
    "credential_required",
    "credential_preferred",
    "experience_required",
    "education_required",
    "availability_or_location",
    "physical_or_environmental",
]
RequirementStrictness = Literal[
    "exact_product",
    "product_family",
    "capability",
    "method_or_standard",
    "credential",
    "contextual",
]
RequirementProvenance = Literal[
    "exact_span",
    "legacy_list_item",
    "derived_field",
    "unlocated_extraction",
]
EvidenceExpectation = Literal[
    "candidate_evidence",
    "verified_fact",
    "assessment_or_evidence",
    "unknown",
]
LegacyRequirementSource = Literal["must", "nice", "tech", "derived"]


class JobRequirement(ExtensibleModel):
    id: str
    job_id: str
    source_text: str
    source_start: int | None = Field(default=None, ge=0)
    source_end: int | None = Field(default=None, ge=0)
    provenance: RequirementProvenance
    parsed_concept_id: str | None = None
    parsed_concept_label: str
    concept_type: TermConceptType
    requirement_kind: RequirementKind
    strictness: RequirementStrictness
    minimum_proficiency: ProficiencyLevel | None = None
    context: dict[str, str] = Field(default_factory=dict)
    importance: float = Field(ge=0.0, le=1.0)
    evidence_expectation: EvidenceExpectation
    recency_constraint: str | None = None
    extraction_confidence: float = Field(ge=0.0, le=1.0)
    taxonomy_revision: str
    extraction_policy_revision: str = JOB_EXTRACTION_POLICY_REVISION
    term_decision_id: str
    legacy_source: LegacyRequirementSource
    legacy_order: int = Field(ge=0)
    exact_non_substitutable: bool = False
    failure_reason: str | None = None

    @model_validator(mode="after")
    def validate_source_span(self) -> JobRequirement:
        if (self.source_start is None) != (self.source_end is None):
            raise ValueError("requirement source span needs both offsets")
        if self.provenance == "exact_span" and self.source_start is None:
            raise ValueError("exact_span provenance requires source offsets")
        if self.source_start is not None and self.source_end is not None:
            if self.source_end < self.source_start:
                raise ValueError("requirement source end precedes start")
        if self.strictness == "credential" and self.concept_type != "credential":
            raise ValueError("credential strictness requires a credential concept")
        return self


class RequirementReconciliationIssue(ExtensibleModel):
    code: Literal[
        "source_span_not_found",
        "legacy_projection_mismatch",
    ]
    requirement_id: str | None = None
    message: str
