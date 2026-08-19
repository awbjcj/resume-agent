"""Evidence-backed candidate assertions over UCCM concepts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from resume_agent.models.base import ExtensibleModel
from resume_agent.taxonomy.term_typing import TermConceptType

ASSERTION_POLICY_REVISION = "profile-assertions-v1"

AssertionStatus = Literal[
    "evidenced",
    "inferred",
    "self_reported",
    "assessed",
    "disputed",
    "unknown",
]
Claimability = Literal[
    "literal_evidenced",
    "supported_inference",
    "self_reported_unverified",
    "assessment_validated",
    "transfer_candidate",
    "unknown",
    "disputed",
]
ProficiencyLevel = Literal[1, 2, 3, 4, 5]
Autonomy = Literal["guided", "independent", "leading", "strategic"]
Complexity = Literal["routine", "varied", "complex", "novel"]
Scope = Literal["individual", "team", "organization", "ecosystem"]


class LegacyAssertionProjection(ExtensibleModel):
    """Inputs retained solely to reproduce the legacy matrix row contract."""

    key: str
    display: str
    aliases: list[str] = Field(default_factory=list)
    category: Literal["hard", "soft", "domain"] | None = None
    inferred: bool = False
    strength: float = 0.0


class CapabilityAssertion(ExtensibleModel):
    id: str
    subject_id: str
    concept_id: str
    concept_type: TermConceptType
    term_decision_id: str
    assertion_status: AssertionStatus
    evidence_fact_ids: list[str] = Field(default_factory=list)
    context: str | None = None
    proficiency_level: ProficiencyLevel | None = None
    autonomy: Autonomy | None = None
    complexity: Complexity | None = None
    responsibility_scope: Scope | None = None
    influence_scope: Scope | None = None
    evidence_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    last_used: str | None = None
    usage_count: int = Field(default=0, ge=0)
    claimability: Claimability
    facts_revision: str
    taxonomy_revision: str
    term_typing_policy_revision: str
    assertion_policy_revision: str = ASSERTION_POLICY_REVISION
    legacy_projection: LegacyAssertionProjection

    @model_validator(mode="after")
    def validate_status_claimability(self) -> CapabilityAssertion:
        allowed: dict[AssertionStatus, set[Claimability]] = {
            "evidenced": {"literal_evidenced"},
            "inferred": {"supported_inference", "transfer_candidate"},
            "self_reported": {"self_reported_unverified"},
            "assessed": {"assessment_validated"},
            "disputed": {"disputed"},
            "unknown": {"unknown"},
        }
        if self.claimability not in allowed[self.assertion_status]:
            raise ValueError(
                f"claimability {self.claimability!r} is invalid for "
                f"assertion status {self.assertion_status!r}"
            )
        if len(self.evidence_fact_ids) != len(set(self.evidence_fact_ids)):
            raise ValueError("evidence_fact_ids must be unique")
        return self


PROFICIENCY_LABELS: dict[ProficiencyLevel, str] = {
    1: "Exposure",
    2: "Developing practitioner",
    3: "Independent practitioner",
    4: "Advanced or lead",
    5: "Expert or strategic authority",
}
