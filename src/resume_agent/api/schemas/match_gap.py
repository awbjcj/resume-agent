"""Match-gap API schemas for the skill-demand graph."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from resume_agent.api.schemas.base import CamelModel
from resume_agent.matching.models import LegacyCoverage, MatchStatus
from resume_agent.models.requirements import (
    EvidenceExpectation,
    LegacyRequirementSource,
    RequirementKind,
    RequirementProvenance,
    RequirementStrictness,
)
from resume_agent.taxonomy.graph_models import CareerLayer, EdgeType
from resume_agent.taxonomy.term_typing import TermConceptType
from resume_agent.tracking.match_gap import normalize_skill


class RefreshClustersIn(CamelModel):
    """Exact visible canonical keys to regroup, bounded at the API boundary."""

    skill_keys: list[str] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def normalize_and_dedupe(self) -> "RefreshClustersIn":
        normalized = list(
            dict.fromkeys(
                token for raw in self.skill_keys if (token := normalize_skill(raw))
            )
        )
        if not normalized:
            raise ValueError("skillKeys must include at least one usable skill key")
        self.skill_keys = normalized
        return self


class RestoreSkillsIn(RefreshClustersIn):
    """Retired keys to return to the backlog; same bounds as a scoped regroup."""


class RestoreSkillsOut(CamelModel):
    restored: int
    restored_skills: list[str]


class RetiredSkillOut(CamelModel):
    key: str
    reason: str
    retired_at: datetime


class GroupingStatusOut(CamelModel):
    state: Literal["uncertain", "failed"]
    reason: str
    last_attempted_at: datetime


class JobLiteOut(CamelModel):
    id: int
    company: str | None = None
    title: str | None = None
    seniority: str | None = None
    status: str


class SkillNodeOut(CamelModel):
    skill: str
    domain_id: str | None = None
    covered: bool
    coverage: Literal["covered", "adjacent", "gap"] = "gap"
    key: str
    members: dict[str, int]
    must: int
    nice: int
    tech: int
    job_count: int
    grouping_status: GroupingStatusOut | None = None

    @model_validator(mode="after")
    def sync_legacy_covered(self) -> "SkillNodeOut":
        if self.covered or self.coverage == "covered":
            self.covered = True
            self.coverage = "covered"
        else:
            self.covered = False
        return self


class DemandEdgeOut(CamelModel):
    job_id: int
    skill: str
    source: Literal["must", "nice", "tech"]
    skill_key: str


class DomainOut(CamelModel):
    id: str
    label: str
    category: str
    essential_score: int
    popular_score: int
    job_count: int
    skill_count: int
    gap_count: int
    adjacent_count: int = 0


class SuggestionStatusOut(CamelModel):
    kind: Literal["skill", "domain"]
    key: str
    state: Literal["ready", "stale"]
    generated_at: datetime


class CategoryOut(CamelModel):
    slug: str
    label: str
    kind: Literal["hard", "soft"]


class SourceSnapshotRevisionOut(CamelModel):
    namespace: str
    version: str
    checksum: str


class TaxonomyRevisionOut(CamelModel):
    internal_graph_version: str = ""
    external_source_snapshots: list[SourceSnapshotRevisionOut] = Field(
        default_factory=list
    )
    crosswalk_revision: str = ""
    tenant_overlay_revision: str = ""
    generated_legacy_map_revision: str = ""
    correction_ledger_revision: str = ""
    lifecycle_state_revision: str = ""
    canonicalization_override_revision: str = ""
    correction_policy_version: str = ""
    matching_policy_version: str = ""
    effective_hash: str = ""


def _legacy_capability_mode() -> Literal["legacy", "shadow", "uccm"]:
    return "legacy"


def _disabled_capability_status() -> Literal[
    "disabled", "shadow", "active", "fallback"
]:
    return "disabled"


class TaxonomyManifestOut(CamelModel):
    generated: str = ""
    corrections: str = ""
    term_type_corrections: str = Field(default_factory=str)
    state: str = ""
    overrides: str = ""
    semantic: str = ""
    capability_mode: Literal["legacy", "shadow", "uccm"] = Field(
        default_factory=_legacy_capability_mode
    )
    capability_effective_mode: Literal["legacy", "shadow", "uccm"] = Field(
        default_factory=_legacy_capability_mode
    )
    capability_status: Literal["disabled", "shadow", "active", "fallback"] = (
        Field(default_factory=_disabled_capability_status)
    )
    capability_error_code: str | None = None
    capability_activation_report_revision: str | None = None
    capability: TaxonomyRevisionOut | None = None


class OverrideConflictOut(CamelModel):
    token: str
    correction_head: str
    override_head: str
    resolution: Literal["override", "forbid_alias"]


class TypedRequirementOut(CamelModel):
    id: str
    job_id: str
    source_text: str
    source_start: int | None = None
    source_end: int | None = None
    provenance: RequirementProvenance
    parsed_concept_id: str | None = None
    parsed_concept_label: str
    concept_type: TermConceptType
    requirement_kind: RequirementKind
    strictness: RequirementStrictness
    minimum_proficiency: int | None = None
    context: dict[str, str]
    importance: float
    evidence_expectation: EvidenceExpectation
    recency_constraint: str | None = None
    extraction_confidence: float
    taxonomy_revision: str
    extraction_policy_revision: str
    term_decision_id: str
    legacy_source: LegacyRequirementSource
    legacy_order: int
    exact_non_substitutable: bool
    failure_reason: str | None = None


class RelationshipStepOut(CamelModel):
    edge_id: str
    from_id: str
    predicate: EdgeType
    to_id: str
    confidence: float


class RelationshipPathOut(CamelModel):
    steps: list[RelationshipStepOut] = Field(default_factory=list)


class MatchFeatureVectorOut(CamelModel):
    canonical_identity: bool
    approved_equivalence: bool
    relationship_predicates: list[EdgeType]
    relationship_direction: str | None = None
    task_overlap: float
    knowledge_overlap: float
    subskill_coverage: float
    tool_family_compatible: bool
    industry_context_match: bool | None = None
    occupation_context_match: bool | None = None
    audience_or_scale_match: bool | None = None
    proficiency_sufficient: bool | None = None
    autonomy_sufficient: bool | None = None
    complexity_sufficient: bool | None = None
    recency_sufficient: bool | None = None
    evidence_directness: float
    evidence_confidence: float | None = None
    requirement_importance: float
    strictness: str
    lexical_similarity: float
    embedding_similarity: float
    learned_domain_match: bool


class MatchV2Out(CamelModel):
    id: str
    requirement_id: str
    status: MatchStatus
    confidence: float
    requirement_concept_id: str | None = None
    requirement_label: str
    assertion_id: str | None = None
    verified_requirement_fact_id: str | None = None
    candidate_concept_id: str | None = None
    candidate_label: str | None = None
    relationship_path: RelationshipPathOut | None = None
    features: MatchFeatureVectorOut
    evidence_fact_ids: list[str]
    explanation_code: str
    recommended_action: str
    matching_policy_revision: str
    taxonomy_revision: str
    facts_revision: str | None = None
    assertion_policy_revision: str | None = None
    extraction_policy_revision: str
    strict_requirement_credit: bool


class ShadowMatchOut(CamelModel):
    legacy_coverage: LegacyCoverage
    v2: MatchV2Out


class ProfileProjectionItemOut(CamelModel):
    concept_id: str
    concept_type: str
    display: str
    assertion_ids: list[str]
    evidence_fact_ids: list[str]


class ProfileLayerProjectionOut(CamelModel):
    layer: CareerLayer
    items: list[ProfileProjectionItemOut]


class EvidenceQualityProjectionOut(CamelModel):
    counts: dict[str, int]
    assertion_ids: list[str]


class DevelopmentNeedOut(CamelModel):
    assertion_id: str
    concept_id: str
    display: str
    reason: Literal[
        "unknown_type",
        "evidence_needed",
        "disputed",
        "level_unknown",
    ]


class UccmProfileProjectionOut(CamelModel):
    layers: list[ProfileLayerProjectionOut]
    evidence_quality: EvidenceQualityProjectionOut
    development_needs: list[DevelopmentNeedOut]


UccmState = Literal["disabled", "ready", "stale", "unavailable"]


def _disabled_uccm_state() -> UccmState:
    return "disabled"


class MatchGapOut(CamelModel):
    target_total: int
    clusters_stale: bool
    jobs: list[JobLiteOut]
    skills: list[SkillNodeOut]
    edges: list[DemandEdgeOut]
    domains: list[DomainOut]
    categories: list[CategoryOut]
    suggestion_statuses: list[SuggestionStatusOut] = Field(default_factory=list)
    taxonomy_generation: str | None = None
    taxonomy_algorithm_version: str = "legacy"
    taxonomy_maintenance_due: bool = True
    unassigned_count: int = 0
    taxonomy_undo_available: bool = False
    taxonomy_revision: str = ""
    taxonomy_manifest: TaxonomyManifestOut | None = None
    override_conflicts: list[OverrideConflictOut] = Field(default_factory=list)
    uccm_state: UccmState = Field(default_factory=_disabled_uccm_state)
    uccm_error_code: str | None = None
    matching_policy_revision: str = Field(default_factory=str)
    profile_facts_revision: str = Field(default_factory=str)
    assertion_policy_revision: str = Field(default_factory=str)
    typed_requirements: list[TypedRequirementOut] = Field(default_factory=list)
    match_results: list[ShadowMatchOut] = Field(default_factory=list)
    profile_projection: UccmProfileProjectionOut | None = None
    # Tokens the classifier judged to name no skill.  They are excluded from the
    # backlog, so they must stay visible somewhere or a wrong call is invisible
    # and irreversible.
    retired_skills: list[RetiredSkillOut] = Field(default_factory=list)
