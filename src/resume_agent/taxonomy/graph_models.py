from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import Field

from resume_agent.models.base import ExtensibleModel
from resume_agent.taxonomy.clusters import ClusterMap

CareerCapabilityMode = Literal["legacy", "shadow", "uccm"]
CareerLayer = Literal[
    "career_core",
    "foundational",
    "transferable_function",
    "domain_industry",
    "occupation_role",
    "enabler",
]
ConceptType = Literal[
    "competency_family",
    "capability",
    "skill",
    "knowledge",
    "work_activity",
    "task",
    "method",
    "standard",
    "tool_technology",
    "artifact",
    "work_style",
    "language",
    "occupation_role",
    "industry_domain",
    "knowledge_domain",
    "credential",
    "requirement",
    "work_context",
    "learning_outcome",
]
EdgeType = Literal[
    "lexical_alias_of",
    "same_as",
    "equivalent_in_context",
    "broader_than",
    "narrower_than",
    "version_of",
    "member_of_family",
    "requires_knowledge",
    "requires_capability",
    "uses_tool",
    "produces_artifact",
    "supports_task",
    "essential_for_role",
    "optional_for_role",
    "applies_in_domain",
    "transferable_to",
    "prerequisite_for",
    "validated_by",
    "aligned_to",
]


class SourceManifest(ExtensibleModel):
    id: str
    namespace: str
    source_id: str
    source_version: str
    source_uri: str
    license_id: str
    attribution: str
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    mapping_status: Literal["native", "adapted", "mapped", "proposed"]
    tenant_scope: Literal[
        "global", "workspace", "tenant", "profile", "proposed_shared"
    ]


class SourceMapping(ExtensibleModel):
    namespace: str
    source_id: str
    source_label: str
    source_definition: str | None = None
    source_version: str
    source_uri: str
    original_hierarchy: list[str] = Field(default_factory=list)
    license_id: str
    attribution: str
    import_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    mapping_status: Literal["native", "adapted", "mapped", "proposed"]
    deprecated: bool = False
    replaced_by: str | None = None


class ConceptDefinition(ExtensibleModel):
    text: str
    locale: str = "en-US"
    source_ref: str


class ConceptAlias(ExtensibleModel):
    label: str
    locale: str = "en-US"
    alias_type: Literal["lexical_variant", "approved_synonym"]
    source_ref: str


class ConceptNode(ExtensibleModel):
    id: str
    type: ConceptType
    preferred_label: str
    normalized_label: str
    definitions: list[ConceptDefinition] = Field(default_factory=list)
    aliases: list[ConceptAlias] = Field(default_factory=list)
    career_layers: list[CareerLayer] = Field(default_factory=list)
    granularity: Literal[
        "family", "cluster", "demonstrable_capability", "atomic_skill", "technique_action"
    ] = "atomic_skill"
    reusability: Literal[
        "transversal",
        "cross_sectoral",
        "sector_specific",
        "occupation_specific",
        "employer_specific",
    ] = "cross_sectoral"
    domains: list[str] = Field(default_factory=list)
    occupations: list[str] = Field(default_factory=list)
    locales: list[str] = Field(default_factory=lambda: ["en-US"])
    jurisdictions: list[str] = Field(default_factory=list)
    status: Literal["active", "proposed", "deprecated", "rejected"] = "active"
    claim_policy: Literal[
        "evidence_required",
        "assessment_or_evidence_required",
        "private_profile_only",
        "never_candidate_claim",
    ] = "evidence_required"
    type_assignment_status: Literal[
        "governed", "legacy_placeholder", "proposed"
    ] = "proposed"
    source_refs: list[str] = Field(min_length=1)
    source_mappings: list[SourceMapping] = Field(default_factory=list)


class ConceptEdge(ExtensibleModel):
    id: str
    subject_id: str
    predicate: EdgeType
    object_id: str
    direction: Literal["directed", "bidirectional"] = "directed"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    status: Literal["approved", "proposed", "rejected", "inactive"] = "approved"
    conditions: dict[str, Any] = Field(default_factory=dict)
    source_refs: list[str] = Field(min_length=1)
    evidence_refs: list[str] = Field(default_factory=list)
    reviewer_ids: list[str] = Field(default_factory=list)
    scope: Literal["global", "tenant", "profile", "proposed_shared"] = "global"
    valid_from: str | None = None
    valid_to: str | None = None
    revision_created: str


class LegacyProjectionMetadata(ExtensibleModel):
    concept_tokens: dict[str, str] = Field(default_factory=dict)
    domain_of: dict[str, str] = Field(default_factory=dict)
    domain_label: dict[str, str] = Field(default_factory=dict)
    category_of: dict[str, str] = Field(default_factory=dict)


class CareerCapabilityGraph(ExtensibleModel):
    model_version: str
    nodes: list[ConceptNode] = Field(default_factory=list)
    edges: list[ConceptEdge] = Field(default_factory=list)
    sources: list[SourceManifest] = Field(default_factory=list)
    legacy_projection: LegacyProjectionMetadata = Field(
        default_factory=LegacyProjectionMetadata
    )


class CorrectionEvent(ExtensibleModel):
    id: str
    scope: Literal["tenant", "profile", "proposed_shared"]
    operation: Literal[
        "alias",
        "add_skill",
        "remove_skill",
        "move_skill",
        "rename_domain",
        "merge_domain",
        "set_domain_category",
        "forbid_alias",
        "ban_skill",
        "set_profile_category",
        "set_profile_group",
    ]
    subject: str
    object: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    source_revision: str


@dataclass(frozen=True)
class SourceSnapshotRevision:
    namespace: str
    version: str
    checksum: str


@dataclass(frozen=True)
class TaxonomyRevision:
    internal_graph_version: str
    external_source_snapshots: tuple[SourceSnapshotRevision, ...]
    crosswalk_revision: str
    tenant_overlay_revision: str
    generated_legacy_map_revision: str
    correction_ledger_revision: str
    lifecycle_state_revision: str
    canonicalization_override_revision: str
    correction_policy_version: str
    matching_policy_version: str
    effective_hash: str


@dataclass(frozen=True)
class EffectiveCapabilitySnapshot:
    graph: CareerCapabilityGraph
    legacy_projection: ClusterMap
    correction_events: tuple[CorrectionEvent, ...]
    revision: TaxonomyRevision
