"""Persistable, explainable Match Engine v2 records."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from resume_agent.models.base import ExtensibleModel
from resume_agent.taxonomy.graph_models import EdgeType

MATCHING_POLICY_REVISION = "uccm-match-v1"

MatchStatus = Literal[
    "verified_exact",
    "verified_equivalent",
    "covered_broader",
    "covered_narrower",
    "transferable",
    "partial",
    "level_gap",
    "context_gap",
    "recency_gap",
    "evidence_gap",
    "tool_gap",
    "credential_gap",
    "unknown",
    "absent",
]
LegacyCoverage = Literal["covered", "adjacent", "gap", "not_evaluated"]


class VerifiedRequirementFact(ExtensibleModel):
    id: str
    fact_type: Literal[
        "credential",
        "work_authorization",
        "security_clearance",
        "location",
        "education",
        "language",
    ]
    normalized_value: str
    display: str
    evidence_fact_id: str
    verification_status: Literal["verified", "asserted", "disputed", "unknown"]
    jurisdiction: str | None = None
    facts_revision: str = ""


class RelationshipStep(ExtensibleModel):
    edge_id: str
    from_id: str
    predicate: EdgeType
    to_id: str
    confidence: float = Field(ge=0.0, le=1.0)


class RelationshipPath(ExtensibleModel):
    steps: list[RelationshipStep] = Field(default_factory=list)


class MatchFeatureVector(ExtensibleModel):
    canonical_identity: bool = False
    approved_equivalence: bool = False
    relationship_predicates: list[EdgeType] = Field(default_factory=list)
    relationship_direction: str | None = None
    task_overlap: float = Field(default=0.0, ge=0.0, le=1.0)
    knowledge_overlap: float = Field(default=0.0, ge=0.0, le=1.0)
    subskill_coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    tool_family_compatible: bool = False
    industry_context_match: bool | None = None
    occupation_context_match: bool | None = None
    audience_or_scale_match: bool | None = None
    proficiency_sufficient: bool | None = None
    autonomy_sufficient: bool | None = None
    complexity_sufficient: bool | None = None
    recency_sufficient: bool | None = None
    evidence_directness: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    requirement_importance: float = Field(ge=0.0, le=1.0)
    strictness: str
    lexical_similarity: float = Field(default=0.0, ge=0.0, le=1.0)
    embedding_similarity: float = Field(default=0.0, ge=0.0, le=1.0)
    learned_domain_match: bool = False


class MatchV2Result(ExtensibleModel):
    id: str
    requirement_id: str
    status: MatchStatus
    confidence: float = Field(ge=0.0, le=1.0)
    requirement_concept_id: str | None = None
    requirement_label: str
    assertion_id: str | None = None
    verified_requirement_fact_id: str | None = None
    candidate_concept_id: str | None = None
    candidate_label: str | None = None
    relationship_path: RelationshipPath | None = None
    features: MatchFeatureVector
    evidence_fact_ids: list[str] = Field(default_factory=list)
    explanation_code: str
    recommended_action: str
    matching_policy_revision: str = MATCHING_POLICY_REVISION
    taxonomy_revision: str
    facts_revision: str | None = None
    assertion_policy_revision: str | None = None
    extraction_policy_revision: str
    strict_requirement_credit: bool = False


class ShadowMatchResult(ExtensibleModel):
    legacy_coverage: LegacyCoverage
    v2: MatchV2Result
