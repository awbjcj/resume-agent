# UCCM Phase 1 Typed Graph Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce the second UCCM delivery phase—a validated, deterministic Career Capability Graph adapter that round-trips the effective legacy taxonomy without changing matching, profile rows, or existing API behavior.

**Architecture:** Keep Phase 0's `EffectiveTaxonomy` as the only application read seam. In `legacy` mode it continues to serve the effective `ClusterMap`; in `shadow` mode it additionally builds and validates an in-memory typed graph; in `uccm` mode it serves the legacy projection derived back from that graph only after an equality guard proves the projection matches the Phase 0 map. Governed UCCM seed concepts and migrated legacy concepts share one graph, while legacy domain/category membership stays in projection metadata and never becomes a semantic edge.

**Tech Stack:** Python 3.13, Pydantic v2 `ExtensibleModel`, frozen dataclass read models, deterministic JSON + SHA-256, pytest, FastAPI/OpenAPI, generated TypeScript contracts, Ruff.

**Spec:** `docs/superpowers/specs/2026-08-19-universal-career-capability-matrix-profile-match-gap-design.md`

## Global Constraints

- **Scope is the second delivery phase only: research Phase 1.** Phase 0's effective-taxonomy seam is a prerequisite. Do not add model-assisted term typing, capability assertions, typed job requirements, Match Engine v2, UCCM profile/match-gap UI, external taxonomy imports, a graph database, or evaluation gold sets.
- **Production matching remains unchanged.** Existing exact, same-domain `adjacent`, and `gap` behavior, ranking, suggestions, evidence planning, and tailoring inputs continue to consume the compatibility `ClusterMap`.
- **Use exactly one deployment setting:** `CAREER_CAPABILITY_MODE=legacy|shadow|uccm`, default `legacy`. Do not add independent graph booleans.
- **Mode behavior is exact:** `legacy` skips graph construction; `shadow` builds and validates the graph but serves the Phase 0 map; `uccm` serves the graph-derived map only when it equals the Phase 0 map. Any validation or equality failure serves the Phase 0 map and records a stable fallback code.
- **No read-time persistence.** Phase 1 builds an immutable in-memory graph from the coherent Phase 0 snapshot. `cluster_map.json`, `taxonomy_corrections.json`, taxonomy state, and profile overrides remain the persisted inputs; no request writes `capability_graph.json`.
- **Legacy terms are not considered typed.** A migrated canonical string uses `type="skill"` only as a compatibility carrier and must have `type_assignment_status="legacy_placeholder"`. Phase 2 is responsible for semantic term typing.
- **Governed seed concepts are not candidate claims.** The six layers, eight career-core families, and twelve transferable work-function families use `claim_policy="never_candidate_claim"` until later assertion policy maps evidence to observable concepts.
- **Learned domains and fixed categories are projection metadata only.** Conversion must not create `same_as`, `equivalent_in_context`, `broader_than`, `narrower_than`, `applies_in_domain`, or `transferable_to` edges from co-membership.
- **Identity collapse is conservative.** Existing aliases become directed `lexical_alias_of` edges. Phase 1 does not infer `same_as` from lexical similarity, domain membership, embeddings, co-occurrence, or shared tools.
- **Stable identity is namespaced and reversible.** Legacy token IDs use percent-encoded normalized tokens, governed seeds use `internal:` IDs, and edge/event IDs use canonical SHA-256 inputs. Build timestamps never participate in graph identity.
- **Validation is fail-closed for the graph and fail-open to legacy behavior.** Duplicate IDs, dangling references, invalid edge signatures, forbidden cycles, missing source manifests, invalid scopes, and nondeterministic projections reject graph activation; they do not corrupt legacy taxonomy data.
- **Preserve Phase 0 revision semantics.** `EffectiveTaxonomy.semantic_revision` remains a content/freshness hash. Raw correction, state, and override component hashes stay trace metadata; two inputs producing identical effective content do not churn cached artifacts.
- **API changes are additive.** Existing match-gap, profile matrix, and resume-version fields keep their names, types, and optionality. The complete capability revision is nested under the existing taxonomy manifest compatibility envelope.
- **No external source content.** `external_source_snapshots` is empty in this phase. The models validate license, attribution, checksum, and version metadata so a later import cannot bypass that contract.
- **Verification is offline.** Use `.\.venv\Scripts\python.exe -m pytest`; no provider key or network call is required. Use `ruff check`, not a repository-wide format rewrite.
- **Execution prerequisite:** start from a branch containing Phase 0 commit `b9ae3157` or its merged equivalent. Preserve unrelated worktree changes.

## File Structure

| File | Responsibility |
| --- | --- |
| `src/resume_agent/taxonomy/graph_models.py` | **Create.** Typed graph vocabulary, graph/source/correction models, `TaxonomyRevision`, and `EffectiveCapabilitySnapshot`. |
| `src/resume_agent/taxonomy/uccm_seeds.py` | **Create.** Six governed layer definitions, eight career-core family nodes, twelve transferable work-function nodes, and the internal source manifest. |
| `src/resume_agent/taxonomy/graph_validation.py` | **Create.** Edge-signature, identity, hierarchy, source, scope, and deterministic validation. |
| `src/resume_agent/taxonomy/graph_adapter.py` | **Create.** Stable IDs, legacy-to-graph conversion, correction-event projection, graph-to-ClusterMap projection, canonical serialization, revision hashing, and equality guard. |
| `src/resume_agent/taxonomy/snapshot.py` | **Modify.** Attach an optional `EffectiveCapabilitySnapshot` and nested complete capability revision to the existing immutable read model. |
| `src/resume_agent/profile/effective.py` | **Modify.** Select `legacy`, `shadow`, or `uccm` inside the one I/O seam and implement safe fallback. |
| `src/resume_agent/config.py` | **Modify.** Add the single `career_capability_mode` setting with default `legacy`. |
| `src/resume_agent/profile/matrix.py` | **Modify.** Persist the nested complete capability revision in `TaxonomyManifestModel`. |
| `src/resume_agent/api/schemas/match_gap.py` | **Modify.** Project the same nested revision additively in `TaxonomyManifestOut`. |
| `contracts/openapi.json`, `contracts/ts/api.ts`, `web/src/lib/api/schema.ts` | **Regenerate.** Keep backend and frontend contract mirrors synchronized. |
| `tests/test_capability_graph_seam.py` | **Create.** Cross-path phase acceptance test, xfailed first and enabled last. |
| `tests/test_capability_graph_models.py` | **Create.** Vocabulary and source-manifest boundary tests. |
| `tests/test_uccm_seeds.py` | **Create.** Exact governed seed counts, IDs, labels, layers, and claim-policy tests. |
| `tests/test_capability_graph_validation.py` | **Create.** Invalid identifiers, edges, cycles, scopes, and source references. |
| `tests/test_capability_graph_adapter.py` | **Create.** Round-trip, provenance, correction replay, stable ordering, and hashing tests. |
| `tests/test_profile_effective.py`, `tests/test_config.py` | **Modify.** Mode selection, fallback, and complete-revision integration tests. |
| `tests/api/test_match_gap.py`, `tests/api/test_schemas_match_gap.py`, `tests/api/test_openapi_contract.py` | **Modify/Test.** Additive wire contract and legacy-payload invariance. |
| `docs/notes/2026-08-19-uccm-phase1-graph-adapter-migration.md` | **Create.** Compatibility projection, revisions, mode behavior, rollback, and retained data. |

---

### Task 1: Cross-seam acceptance test, xfailed before implementation

**Files:**

- Create: `tests/test_capability_graph_seam.py`

**Interfaces:**

- Consumes: Phase 0 `build_effective_taxonomy(profile_dir, corrections_path=corrections_path)`, `build_matrix(facts, taxonomy)`, `ClusterMap`, and `TaxonomyCorrections`.
- Produces: the executable phase gate. Task 9 removes the strict xfail after all integration and contract work is complete.

- [ ] **Step 1: Write the acceptance test with imports inside the test body**

```python
from __future__ import annotations

import pytest

from resume_agent.models.profile import Contact, ProfileFacts, Skill
from resume_agent.profile.matrix import build_matrix
from resume_agent.taxonomy.clusters import ClusterMap, save_cluster_map
from resume_agent.taxonomy.corrections import (
    TaxonomyCorrections,
    save_taxonomy_corrections,
)


def _seed(tmp_path):
    profile_dir = tmp_path / "profile"
    profile_dir.mkdir(parents=True)
    save_cluster_map(
        ClusterMap(
            aliases={"js": "javascript"},
            domain_of={"javascript": "web-langs", "react": "web-frameworks"},
            domain_label={
                "web-langs": "Web Languages",
                "web-frameworks": "Web Frameworks",
            },
            category_of={
                "web-langs": "languages",
                "web-frameworks": "frontend-web",
            },
        ),
        profile_dir / "cluster_map.json",
    )
    corrections_path = tmp_path / "taxonomy" / "taxonomy_corrections.json"
    save_taxonomy_corrections(
        TaxonomyCorrections(
            aliases={"reactjs": "react"},
            domain_merges={"web-frameworks": "web-langs"},
            domain_renames={"web-langs": "Web Development"},
        ),
        corrections_path,
    )
    facts = ProfileFacts(
        contact=Contact(name="Candidate"),
        skills={"hard": [Skill(name="ReactJS"), Skill(name="JavaScript")]},
    )
    return profile_dir, corrections_path, facts


@pytest.mark.xfail(
    strict=True,
    reason="UCCM Phase 1 graph adapter and deployment modes are not implemented",
)
def test_uccm_mode_round_trips_the_effective_taxonomy_without_row_drift(tmp_path):
    from resume_agent.profile.effective import build_effective_taxonomy
    from resume_agent.taxonomy.graph_adapter import graph_to_cluster_map

    profile_dir, corrections_path, facts = _seed(tmp_path)
    legacy = build_effective_taxonomy(
        profile_dir,
        corrections_path=corrections_path,
        mode="legacy",
    )
    uccm = build_effective_taxonomy(
        profile_dir,
        corrections_path=corrections_path,
        mode="uccm",
    )

    assert uccm.capability_snapshot is not None
    assert graph_to_cluster_map(uccm.capability_snapshot.graph) == legacy.cluster_map
    assert uccm.cluster_map == legacy.cluster_map
    assert {event.operation for event in uccm.capability_snapshot.correction_events} >= {
        "alias",
        "merge_domain",
        "rename_domain",
    }
    assert uccm.capability_snapshot.revision.internal_graph_version
    assert uccm.manifest.capability is not None
    assert uccm.manifest.capability.effective_hash == uccm.semantic_revision

    legacy_rows = [row.model_dump() for row in build_matrix(facts, legacy).rows]
    uccm_rows = [row.model_dump() for row in build_matrix(facts, uccm).rows]
    assert uccm_rows == legacy_rows
```

- [ ] **Step 2: Run the new test and verify it is an xfail, not a collection error**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_capability_graph_seam.py -v`

Expected: `1 xfailed`. An import error means a future symbol escaped the test body; keep all Phase 1 imports inside the test.

- [ ] **Step 3: Run the Phase 0 seam tests to capture the green baseline**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_effective_taxonomy_seam.py tests/test_profile_effective.py tests/test_taxonomy_snapshot.py -v`

Expected: PASS with the new Phase 1 test still isolated.

- [ ] **Step 4: Commit the executable acceptance boundary**

```powershell
git add tests/test_capability_graph_seam.py
git commit -m "test(taxonomy): define UCCM graph-adapter acceptance seam"
```

---

### Task 2: Typed graph, provenance, correction, and revision models

**Files:**

- Create: `src/resume_agent/taxonomy/graph_models.py`
- Create: `tests/test_capability_graph_models.py`

**Interfaces:**

- Consumes: `ExtensibleModel` and legacy `ClusterMap`.
- Produces: `CareerCapabilityMode`, `CareerLayer`, `ConceptType`, `EdgeType`, `SourceManifest`, `SourceMapping`, `ConceptNode`, `ConceptEdge`, `LegacyProjectionMetadata`, `CareerCapabilityGraph`, `CorrectionEvent`, `SourceSnapshotRevision`, `TaxonomyRevision`, and `EffectiveCapabilitySnapshot`.

- [ ] **Step 1: Write tests for the closed vocabulary and source boundary**

```python
from __future__ import annotations

import pytest
from pydantic import ValidationError

from resume_agent.taxonomy.graph_models import (
    CareerCapabilityGraph,
    ConceptEdge,
    ConceptNode,
    LegacyProjectionMetadata,
    SourceManifest,
)


def _source() -> SourceManifest:
    return SourceManifest(
        id="source:internal:test:1",
        namespace="internal",
        source_id="test",
        source_version="1",
        source_uri="internal://test",
        license_id="internal-proprietary",
        attribution="Resume Agent test fixture",
        checksum="a" * 64,
        mapping_status="native",
        tenant_scope="global",
    )


def test_graph_models_preserve_all_matching_relevant_facets():
    node = ConceptNode(
        id="internal:capability:financial-modeling",
        type="capability",
        preferred_label="Financial Modeling",
        normalized_label="financial modeling",
        career_layers=["occupation_role"],
        granularity="demonstrable_capability",
        reusability="cross_sectoral",
        domains=["internal:domain:finance"],
        occupations=["internal:role:financial-analyst"],
        locales=["en-US"],
        jurisdictions=[],
        status="active",
        claim_policy="evidence_required",
        type_assignment_status="governed",
        source_refs=["source:internal:test:1"],
    )
    assert node.type == "capability"
    assert node.career_layers == ["occupation_role"]
    assert node.claim_policy == "evidence_required"


def test_source_mapping_retains_a_future_external_record_without_importing_it():
    from resume_agent.taxonomy.graph_models import SourceMapping

    mapping = SourceMapping(
        namespace="example_external",
        source_id="record-42",
        source_label="External label",
        source_definition="External definition",
        source_version="2026.08",
        source_uri="https://example.invalid/source/record-42",
        original_hierarchy=["root", "branch", "record-42"],
        license_id="CC-BY-4.0",
        attribution="Example external source",
        import_checksum="c" * 64,
        mapping_status="proposed",
        deprecated=False,
    )
    assert mapping.original_hierarchy[-1] == mapping.source_id
    assert mapping.replaced_by is None


def test_unknown_concept_and_edge_literals_are_rejected():
    with pytest.raises(ValidationError):
        ConceptNode(
            id="internal:bad:x",
            type="mystery",
            preferred_label="X",
            normalized_label="x",
            source_refs=["source:internal:test:1"],
        )
    with pytest.raises(ValidationError):
        ConceptEdge(
            id="edge:bad",
            subject_id="internal:skill:a",
            predicate="looks_like",
            object_id="internal:skill:b",
            source_refs=["source:internal:test:1"],
        )


def test_graph_can_hold_projection_metadata_without_semantic_domain_edges():
    graph = CareerCapabilityGraph(
        model_version="0.1.0-design",
        nodes=[],
        edges=[],
        sources=[_source()],
        legacy_projection=LegacyProjectionMetadata(
            concept_tokens={},
            domain_of={},
            domain_label={"web": "Web"},
            category_of={"web": "frontend-web"},
        ),
    )
    assert graph.legacy_projection.category_of == {"web": "frontend-web"}
```

- [ ] **Step 2: Run the tests and verify the module is missing**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_capability_graph_models.py -v`

Expected: collection FAIL because `resume_agent.taxonomy.graph_models` does not exist.

- [ ] **Step 3: Add the exact vocabulary aliases and persisted models**

```python
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
```

- [ ] **Step 4: Run the model tests and lint**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_capability_graph_models.py -v`

Run: `ruff check src/resume_agent/taxonomy/graph_models.py tests/test_capability_graph_models.py`

Expected: PASS.

- [ ] **Step 5: Commit the domain vocabulary**

```powershell
git add src/resume_agent/taxonomy/graph_models.py tests/test_capability_graph_models.py
git commit -m "feat(taxonomy): add typed career capability graph models"
```

---

### Task 3: Governed UCCM layer, core-family, and work-function seeds

**Files:**

- Create: `src/resume_agent/taxonomy/uccm_seeds.py`
- Create: `tests/test_uccm_seeds.py`

**Interfaces:**

- Consumes: `CareerLayer`, `ConceptNode`, and `SourceManifest` from Task 2.
- Produces: `UCCM_MODEL_VERSION`, `CAREER_LAYERS`, `UCCM_SOURCE`, `uccm_seed_nodes() -> tuple[ConceptNode, ...]`, with exactly 20 nodes: 8 career-core families and 12 transferable work-function families.

- [ ] **Step 1: Write exact seed-contract tests**

```python
from resume_agent.taxonomy.uccm_seeds import (
    CAREER_LAYERS,
    UCCM_SOURCE,
    uccm_seed_nodes,
)


def test_uccm_seed_catalog_has_six_layers_eight_core_and_twelve_functions():
    nodes = uccm_seed_nodes()
    core = [node for node in nodes if node.career_layers == ["career_core"]]
    functions = [
        node for node in nodes if node.career_layers == ["transferable_function"]
    ]
    assert [layer.id for layer in CAREER_LAYERS] == [
        "career_core",
        "foundational",
        "transferable_function",
        "domain_industry",
        "occupation_role",
        "enabler",
    ]
    assert len(core) == 8
    assert len(functions) == 12
    assert len(nodes) == len({node.id for node in nodes}) == 20


def test_governed_projection_families_are_not_candidate_claims():
    for node in uccm_seed_nodes():
        assert node.type_assignment_status == "governed"
        assert node.claim_policy == "never_candidate_claim"
        assert node.source_refs == [UCCM_SOURCE.id]


def test_seed_labels_and_ids_are_product_owned_and_stable():
    by_id = {node.id: node.preferred_label for node in uccm_seed_nodes()}
    assert by_id["internal:competency-family:reasoning-judgment-problem-solving"] == (
        "Reasoning, Judgment, and Problem Solving"
    )
    assert by_id["internal:work-function:monitor-assure"] == "Monitor and Assure"
```

- [ ] **Step 2: Run the tests and verify the seed module is missing**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_uccm_seeds.py -v`

Expected: collection FAIL because `uccm_seeds.py` does not exist.

- [ ] **Step 3: Define the immutable source rows and all 20 governed nodes**

Use these exact identifiers and labels as the data rows passed to one `_seed_node` helper:

```python
CORE_FAMILIES = (
    ("career-navigation-continuous-learning", "Career Navigation and Continuous Learning"),
    ("reasoning-judgment-problem-solving", "Reasoning, Judgment, and Problem Solving"),
    ("communication-sensemaking", "Communication and Sensemaking"),
    ("collaboration-relationship-management", "Collaboration and Relationship Management"),
    ("professional-responsibility-execution", "Professional Responsibility and Execution"),
    ("leadership-influence-mobilization", "Leadership, Influence, and Mobilization"),
    ("inclusive-intercultural-practice", "Inclusive and Intercultural Practice"),
    ("digital-data-ai-fluency", "Digital, Data, and AI Fluency"),
)

WORK_FUNCTIONS = (
    ("discover-research", "Discover and Research"),
    ("analyze-diagnose", "Analyze and Diagnose"),
    ("decide-advise", "Decide and Advise"),
    ("design-create", "Design and Create"),
    ("plan-coordinate", "Plan and Coordinate"),
    ("execute-operate", "Execute and Operate"),
    ("monitor-assure", "Monitor and Assure"),
    ("communicate-influence", "Communicate and Influence"),
    ("collaborate-facilitate", "Collaborate and Facilitate"),
    ("serve-support-care", "Serve, Support, and Care"),
    ("teach-develop", "Teach and Develop"),
    ("lead-manage", "Lead and Manage"),
)
```

Add a `CareerLayerDefinition` frozen dataclass and the exact six labels from `docs/uccm-reference-model.yaml`. Build the source checksum from canonical JSON containing `CAREER_LAYERS`, `CORE_FAMILIES`, and `WORK_FUNCTIONS`; do not hard-code a checksum that can drift from the rows.

```python
def _seed_node(
    *, namespace: str, row: tuple[str, str], layer: CareerLayer
) -> ConceptNode:
    slug, label = row
    return ConceptNode(
        id=f"internal:{namespace}:{slug}",
        type="competency_family" if layer == "career_core" else "work_activity",
        preferred_label=label,
        normalized_label=label.casefold(),
        career_layers=[layer],
        granularity="family",
        reusability="transversal" if layer == "career_core" else "cross_sectoral",
        claim_policy="never_candidate_claim",
        type_assignment_status="governed",
        source_refs=[UCCM_SOURCE.id],
    )


def uccm_seed_nodes() -> tuple[ConceptNode, ...]:
    nodes = [
        _seed_node(namespace="competency-family", row=row, layer="career_core")
        for row in CORE_FAMILIES
    ]
    nodes.extend(
        _seed_node(
            namespace="work-function",
            row=row,
            layer="transferable_function",
        )
        for row in WORK_FUNCTIONS
    )
    return tuple(sorted(nodes, key=lambda node: node.id))
```

The source manifest must use `namespace="internal"`, `source_id="uccm"`, `source_version="0.1.0-design"`, `source_uri="repo://docs/uccm-reference-model.yaml"`, `license_id="internal-proprietary"`, `mapping_status="native"`, and `tenant_scope="global"`.

- [ ] **Step 4: Run the seed tests and lint**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_uccm_seeds.py -v`

Run: `ruff check src/resume_agent/taxonomy/uccm_seeds.py tests/test_uccm_seeds.py`

Expected: PASS.

- [ ] **Step 5: Commit the governed product seed**

```powershell
git add src/resume_agent/taxonomy/uccm_seeds.py tests/test_uccm_seeds.py
git commit -m "feat(taxonomy): seed governed UCCM projection families"
```

---

### Task 4: Deterministic graph validation

**Files:**

- Create: `src/resume_agent/taxonomy/graph_validation.py`
- Create: `tests/test_capability_graph_validation.py`

**Interfaces:**

- Consumes: graph models from Task 2.
- Produces: `GraphValidationIssue`, `GraphValidationError`, `GraphValidationError.single(code, subject)`, `EDGE_SIGNATURES`, and `validate_capability_graph(graph) -> None`.

- [ ] **Step 1: Write focused invariant tests**

```python
from __future__ import annotations

import pytest

from resume_agent.taxonomy.graph_models import (
    CareerCapabilityGraph,
    ConceptEdge,
    ConceptNode,
    LegacyProjectionMetadata,
    SourceManifest,
)
from resume_agent.taxonomy.graph_validation import (
    GraphValidationError,
    validate_capability_graph,
)


def _source() -> SourceManifest:
    return SourceManifest(
        id="source:internal:test:1",
        namespace="internal",
        source_id="test",
        source_version="1",
        source_uri="internal://test",
        license_id="internal-proprietary",
        attribution="Test",
        checksum="b" * 64,
        mapping_status="native",
        tenant_scope="global",
    )


def _node(node_id: str, type_: str = "skill") -> ConceptNode:
    return ConceptNode(
        id=node_id,
        type=type_,
        preferred_label=node_id.rsplit(":", 1)[-1],
        normalized_label=node_id.rsplit(":", 1)[-1],
        type_assignment_status="legacy_placeholder",
        source_refs=["source:internal:test:1"],
    )


def _graph(nodes, edges=()):
    return CareerCapabilityGraph(
        model_version="0.1.0-design",
        nodes=list(nodes),
        edges=list(edges),
        sources=[_source()],
        legacy_projection=LegacyProjectionMetadata(),
    )


def test_duplicate_node_ids_and_dangling_edges_are_rejected():
    edge = ConceptEdge(
        id="edge:1",
        subject_id="legacy:skill:a",
        predicate="lexical_alias_of",
        object_id="legacy:skill:missing",
        revision_created="r1",
        source_refs=["source:internal:test:1"],
    )
    with pytest.raises(GraphValidationError) as exc:
        validate_capability_graph(
            _graph([_node("legacy:skill:a"), _node("legacy:skill:a")], [edge])
        )
    assert {issue.code for issue in exc.value.issues} == {
        "duplicate_node_id",
        "dangling_object",
    }


def test_alias_and_hierarchy_cycles_are_rejected():
    nodes = [_node("legacy:skill:a"), _node("legacy:skill:b")]
    edges = [
        ConceptEdge(
            id="edge:a-b",
            subject_id="legacy:skill:a",
            predicate="lexical_alias_of",
            object_id="legacy:skill:b",
            revision_created="r1",
            source_refs=["source:internal:test:1"],
        ),
        ConceptEdge(
            id="edge:b-a",
            subject_id="legacy:skill:b",
            predicate="lexical_alias_of",
            object_id="legacy:skill:a",
            revision_created="r1",
            source_refs=["source:internal:test:1"],
        ),
    ]
    with pytest.raises(GraphValidationError) as exc:
        validate_capability_graph(_graph(nodes, edges))
    assert "alias_cycle" in {issue.code for issue in exc.value.issues}


def test_tools_cannot_be_declared_essential_for_a_non_role_target():
    nodes = [
        _node("internal:tool:excel", "tool_technology"),
        _node("internal:skill:analysis", "skill"),
    ]
    edge = ConceptEdge(
        id="edge:bad-signature",
        subject_id="internal:tool:excel",
        predicate="essential_for_role",
        object_id="internal:skill:analysis",
        revision_created="r1",
        source_refs=["source:internal:test:1"],
    )
    with pytest.raises(GraphValidationError) as exc:
        validate_capability_graph(_graph(nodes, [edge]))
    assert "invalid_edge_signature" in {issue.code for issue in exc.value.issues}
```

- [ ] **Step 2: Run the tests and verify the validator is missing**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_capability_graph_validation.py -v`

Expected: collection FAIL because `graph_validation.py` does not exist.

- [ ] **Step 3: Implement deterministic issue collection and edge signatures**

Use immutable subject/object sets. The exact signature rules are:

```python
CAPABILITY_LIKE = frozenset(
    {"competency_family", "capability", "skill", "work_activity", "task", "method"}
)
KNOWLEDGE_LIKE = frozenset({"knowledge", "knowledge_domain"})
DOMAIN_TYPES = frozenset({"industry_domain", "knowledge_domain"})
ROLE_TYPES = frozenset({"occupation_role"})
TOOL_TYPES = frozenset({"tool_technology", "language"})
ARTIFACT_TYPES = frozenset({"artifact"})
CREDENTIAL_TYPES = frozenset({"credential", "standard"})
ALL_TYPES = frozenset(
    {
        "competency_family", "capability", "skill", "knowledge", "work_activity",
        "task", "method", "standard", "tool_technology", "artifact", "work_style",
        "language", "occupation_role", "industry_domain", "knowledge_domain",
        "credential", "requirement", "work_context", "learning_outcome",
    }
)

EDGE_SIGNATURES = {
    "lexical_alias_of": (ALL_TYPES, ALL_TYPES),
    "same_as": (ALL_TYPES, ALL_TYPES),
    "equivalent_in_context": (ALL_TYPES, ALL_TYPES),
    "broader_than": (ALL_TYPES - {"requirement"}, ALL_TYPES - {"requirement"}),
    "narrower_than": (ALL_TYPES - {"requirement"}, ALL_TYPES - {"requirement"}),
    "version_of": (ALL_TYPES - {"requirement", "work_context"}, ALL_TYPES - {"requirement", "work_context"}),
    "member_of_family": (CAPABILITY_LIKE | TOOL_TYPES | CREDENTIAL_TYPES, {"competency_family", "capability", "tool_technology", "standard"}),
    "requires_knowledge": (CAPABILITY_LIKE | ROLE_TYPES, KNOWLEDGE_LIKE),
    "requires_capability": (CAPABILITY_LIKE | ROLE_TYPES, {"capability", "skill"}),
    "uses_tool": (CAPABILITY_LIKE | ROLE_TYPES, TOOL_TYPES),
    "produces_artifact": (CAPABILITY_LIKE | ROLE_TYPES, ARTIFACT_TYPES),
    "supports_task": ({"capability", "skill", "knowledge", "method", "tool_technology"}, {"task", "work_activity"}),
    "essential_for_role": (CAPABILITY_LIKE | KNOWLEDGE_LIKE | TOOL_TYPES | CREDENTIAL_TYPES, ROLE_TYPES),
    "optional_for_role": (CAPABILITY_LIKE | KNOWLEDGE_LIKE | TOOL_TYPES | CREDENTIAL_TYPES, ROLE_TYPES),
    "applies_in_domain": (ALL_TYPES - {"requirement"}, DOMAIN_TYPES),
    "transferable_to": (CAPABILITY_LIKE, CAPABILITY_LIKE),
    "prerequisite_for": (CAPABILITY_LIKE | KNOWLEDGE_LIKE | CREDENTIAL_TYPES, CAPABILITY_LIKE | ROLE_TYPES | {"learning_outcome"}),
    "validated_by": (CAPABILITY_LIKE | KNOWLEDGE_LIKE, CREDENTIAL_TYPES),
    "aligned_to": (ALL_TYPES, ALL_TYPES),
}
```

`validate_capability_graph` must collect and sort issues by `(code, subject)` before raising once. Validate all of these rules in one pass:

- node, edge, and source IDs are unique and non-empty; node IDs match `namespace:kind:value`, while edge/source IDs match their documented `edge:`/`source:` prefixes;
- every node and edge `source_ref` exists;
- every edge subject and object exists;
- subject and object types satisfy `EDGE_SIGNATURES`;
- `lexical_alias_of` joins the same concept type, is directed, and forms no cycle;
- `same_as` and `equivalent_in_context` are bidirectional; every other predicate is directed;
- combined `broader_than` and reversed `narrower_than` relations form no cycle;
- tenant/profile edges use their matching scope and global edges cannot reference a tenant-only source;
- namespaces other than `internal`, `legacy_cluster_map`, `tenant_corrections`, and `profile_overrides` are treated as external and must have non-empty version, URI, license, attribution, and 64-character checksum;
- every concept ID used by `legacy_projection` exists; label/category entries may reference only projected domains and every present category slug must be in `SKILL_GROUPS`. A missing legacy domain label remains valid and round-trips unchanged because current `ClusterMap` readers fall back to the domain ID.

- [ ] **Step 4: Run validator tests and lint**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_capability_graph_validation.py -v`

Run: `ruff check src/resume_agent/taxonomy/graph_validation.py tests/test_capability_graph_validation.py`

Expected: PASS.

- [ ] **Step 5: Commit validation separately from conversion**

```powershell
git add src/resume_agent/taxonomy/graph_validation.py tests/test_capability_graph_validation.py
git commit -m "feat(taxonomy): validate capability graph invariants"
```

---

### Task 5: Legacy ClusterMap conversion, correction events, and exact reverse projection

**Files:**

- Create: `src/resume_agent/taxonomy/graph_adapter.py`
- Create: `tests/test_capability_graph_adapter.py`

**Interfaces:**

- Consumes: `ClusterMap`, `TaxonomyCorrections`, `OverrideView`, Task 2 models, Task 3 seeds, and Task 4 validation.
- Produces: `legacy_concept_id(token) -> str`, `cluster_map_to_graph(cmap, *, generated_revision, correction_revision, override_revision, corrections=None, overrides=None) -> tuple[CareerCapabilityGraph, tuple[CorrectionEvent, ...]]`, and `graph_to_cluster_map(graph) -> ClusterMap`.

- [ ] **Step 1: Write round-trip, non-transfer, provenance, and idempotence tests**

```python
from __future__ import annotations

from resume_agent.profile.matrix import Overrides
from resume_agent.taxonomy.clusters import ClusterMap
from resume_agent.taxonomy.corrections import TaxonomyCorrections
from resume_agent.taxonomy.graph_adapter import (
    cluster_map_to_graph,
    graph_to_cluster_map,
    legacy_concept_id,
)


def _map() -> ClusterMap:
    return ClusterMap(
        aliases={"js": "javascript", "reactjs": "react"},
        domain_of={"javascript": "web-langs", "react": "web-frameworks"},
        domain_label={
            "web-langs": "Web Languages",
            "web-frameworks": "Web Frameworks",
        },
        category_of={
            "web-langs": "languages",
            "web-frameworks": "frontend-web",
        },
    )


def test_effective_cluster_map_round_trips_exactly_through_the_graph():
    graph, _ = cluster_map_to_graph(
        _map(),
        generated_revision="1" * 64,
        correction_revision="2" * 64,
        override_revision="3" * 64,
    )
    assert graph_to_cluster_map(graph) == _map()
    assert legacy_concept_id("C++") == "legacy:skill:c%2B%2B"


def test_domain_and_category_membership_never_becomes_a_semantic_edge():
    graph, _ = cluster_map_to_graph(
        _map(),
        generated_revision="1" * 64,
        correction_revision="2" * 64,
        override_revision="3" * 64,
    )
    assert {edge.predicate for edge in graph.edges} == {"lexical_alias_of"}
    assert graph.legacy_projection.domain_label["web-langs"] == "Web Languages"


def test_legacy_nodes_are_explicitly_untyped_placeholders():
    graph, _ = cluster_map_to_graph(
        _map(),
        generated_revision="1" * 64,
        correction_revision="2" * 64,
        override_revision="3" * 64,
    )
    legacy_nodes = [node for node in graph.nodes if node.id.startswith("legacy:")]
    assert legacy_nodes
    assert {node.type for node in legacy_nodes} == {"skill"}
    assert {node.type_assignment_status for node in legacy_nodes} == {
        "legacy_placeholder"
    }


def test_correction_and_profile_override_events_are_stable_and_scoped():
    corrections = TaxonomyCorrections(
        aliases={"reactjs": "react"},
        domain_merges={"old-web": "web-frameworks"},
        added_skills=["graphql"],
    )
    overrides = Overrides(
        forbid_alias=[["js", "javascript"]],
        group={"react": "frameworks"},
    )
    first_graph, first_events = cluster_map_to_graph(
        _map(),
        generated_revision="1" * 64,
        correction_revision="2" * 64,
        override_revision="3" * 64,
        corrections=corrections,
        overrides=overrides,
    )
    second_graph, second_events = cluster_map_to_graph(
        _map(),
        generated_revision="1" * 64,
        correction_revision="2" * 64,
        override_revision="3" * 64,
        corrections=corrections,
        overrides=overrides,
    )
    assert first_events == second_events
    assert first_graph == second_graph
    assert {event.scope for event in first_events} == {"tenant", "profile"}
    assert {event.operation for event in first_events} == {
        "alias",
        "merge_domain",
        "add_skill",
        "forbid_alias",
        "set_profile_group",
    }
```

- [ ] **Step 2: Run the adapter tests and verify the module is missing**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_capability_graph_adapter.py -v`

Expected: collection FAIL because `graph_adapter.py` does not exist.

- [ ] **Step 3: Implement stable identifiers and source selection**

```python
def legacy_concept_id(token: str) -> str:
    normalized = normalize_skill(token)
    if not normalized:
        raise ValueError("legacy concept token must normalize to a non-empty value")
    return f"legacy:skill:{quote(normalized, safe='')}"


def _stable_id(namespace: str, payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"{namespace}:{hashlib.sha256(encoded).hexdigest()[:24]}"
```

Create three source manifests in addition to `UCCM_SOURCE`:

- generated: `source:legacy-cluster-map:<generated_revision>`, `namespace="legacy_cluster_map"`, source scope `workspace` and edge scope `tenant` because the current workspace is the tenant isolation boundary;
- correction ledger: `source:tenant-corrections:<correction_revision>`, `namespace="tenant_corrections"`, scope `tenant`;
- profile override: `source:profile-overrides:<override_revision>`, `namespace="profile_overrides"`, scope `profile`.

Use `license_id="workspace-private"`, repository-relative `source_uri` values, exact component hashes as checksums, and `mapping_status="adapted"`. Alias edges choose the profile source first, correction source second, and generated source last. Canonical and alias nodes use `type="skill"`, `type_assignment_status="legacy_placeholder"`, no career layer, and `claim_policy="evidence_required"`. Each legacy node also gets one `SourceMapping` containing its normalized source token, applicable component version, `workspace://profile/cluster_map.json`, `license_id="workspace-private"`, attribution, the component checksum, and `mapping_status="adapted"`; this preserves record-level provenance without overloading concept identity.

- [ ] **Step 4: Project all existing correction fields into stable events**

Use one helper whose ID hashes `(scope, operation, subject, object, payload, source_revision)`. Emit events in sorted order for every current persisted operation:

```python
for token, target in sorted(corrections.aliases.items()):
    add("tenant", "alias", token, target, {}, correction_revision)
for token in sorted(corrections.added_skills):
    add("tenant", "add_skill", token, None, {}, correction_revision)
for token in sorted(corrections.removed_skills):
    add("tenant", "remove_skill", token, None, {}, correction_revision)
for token, domain in sorted(corrections.skill_domain.items()):
    add("tenant", "move_skill", token, domain, {}, correction_revision)
for domain, label in sorted(corrections.domain_renames.items()):
    add("tenant", "rename_domain", domain, label, {}, correction_revision)
for loser, winner in sorted(corrections.domain_merges.items()):
    add("tenant", "merge_domain", loser, winner, {}, correction_revision)
for domain, category in sorted(corrections.domain_category.items()):
    add("tenant", "set_domain_category", domain, category, {}, correction_revision)
if overrides is not None:
    for pair in sorted(tuple(sorted(pair)) for pair in overrides.forbid_alias if len(pair) == 2):
        add("profile", "forbid_alias", pair[0], pair[1], {}, override_revision)
    for token in sorted(overrides.ban):
        add("profile", "ban_skill", token, None, {}, override_revision)
    for token, category in sorted(overrides.category.items()):
        add("profile", "set_profile_category", token, category, {}, override_revision)
    for token, group in sorted(overrides.group.items()):
        add("profile", "set_profile_group", token, group, {}, override_revision)
```

`overrides.alias` is emitted as a profile-scoped `alias` event and must take precedence over a tenant alias in source assignment, matching Phase 0 semantics.

- [ ] **Step 5: Build projection metadata and the reverse adapter**

`cluster_map_to_graph` must:

1. Include all alias keys, alias targets, and `domain_of` keys as legacy nodes.
2. Add the 20 governed seed nodes without putting them in `legacy_projection.concept_tokens`.
3. Add only `lexical_alias_of` edges for legacy aliases.
4. Store `domain_of` keyed by legacy concept ID and copy `domain_label`/`category_of` byte-for-byte into `LegacyProjectionMetadata`.
5. Sort nodes, edges, sources, and correction events by stable ID.
6. Call `validate_capability_graph` before returning.

`graph_to_cluster_map` must read only `legacy_projection` plus approved, active `lexical_alias_of` edges; resolve each edge through `concept_tokens`; flatten chains; reject cycles; and return sorted dictionaries. It must ignore all governed seed nodes and every non-lexical edge.

- [ ] **Step 6: Run adapter and existing alias tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_capability_graph_adapter.py tests/test_taxonomy_clusters.py tests/test_taxonomy_corrections.py -v`

Run: `ruff check src/resume_agent/taxonomy/graph_adapter.py tests/test_capability_graph_adapter.py`

Expected: PASS.

- [ ] **Step 7: Commit the compatibility adapter**

```powershell
git add src/resume_agent/taxonomy/graph_adapter.py tests/test_capability_graph_adapter.py
git commit -m "feat(taxonomy): round-trip legacy taxonomy through capability graph"
```

---

### Task 6: Canonical serialization and complete capability revision

**Files:**

- Modify: `src/resume_agent/taxonomy/graph_adapter.py`
- Modify: `tests/test_capability_graph_adapter.py`

**Interfaces:**

- Consumes: Task 5 graph and correction event output.
- Produces: `canonical_graph_json(graph) -> str`, `graph_revision(graph) -> str`, `combine_projection_revision(base_projection_revision, effective_hash) -> str`, `build_capability_snapshot(cmap, *, generated_revision, correction_revision, lifecycle_revision, override_revision, base_effective_hash, corrections=None, overrides=None) -> EffectiveCapabilitySnapshot`, and constants `CORRECTION_POLICY_VERSION="taxonomy-corrections-v1"`, `LEGACY_MATCHING_POLICY_VERSION="legacy-exact-adjacent-gap-v1"`.

- [ ] **Step 1: Add deterministic serialization and revision tests**

```python
def test_graph_json_and_revision_ignore_input_dictionary_order():
    first = ClusterMap(
        aliases={"py": "python", "js": "javascript"},
        domain_of={"python": "backend", "javascript": "web"},
        domain_label={"backend": "Backend", "web": "Web"},
        category_of={"backend": "backend-apis", "web": "frontend-web"},
    )
    second = ClusterMap(
        aliases={"js": "javascript", "py": "python"},
        domain_of={"javascript": "web", "python": "backend"},
        domain_label={"web": "Web", "backend": "Backend"},
        category_of={"web": "frontend-web", "backend": "backend-apis"},
    )
    first_graph, _ = cluster_map_to_graph(
        first,
        generated_revision="1" * 64,
        correction_revision="2" * 64,
        override_revision="3" * 64,
    )
    second_graph, _ = cluster_map_to_graph(
        second,
        generated_revision="1" * 64,
        correction_revision="2" * 64,
        override_revision="3" * 64,
    )
    assert canonical_graph_json(first_graph) == canonical_graph_json(second_graph)
    assert graph_revision(first_graph) == graph_revision(second_graph)


def test_complete_revision_records_components_without_treating_timestamps_as_identity():
    snapshot = build_capability_snapshot(
        _map(),
        generated_revision="1" * 64,
        correction_revision="2" * 64,
        lifecycle_revision="3" * 64,
        override_revision="4" * 64,
        base_effective_hash="5" * 64,
    )
    revision = snapshot.revision
    assert len(revision.internal_graph_version) == 64
    assert revision.external_source_snapshots == ()
    assert len(revision.crosswalk_revision) == 64
    assert revision.tenant_overlay_revision == "2" * 64
    assert revision.generated_legacy_map_revision == "1" * 64
    assert revision.correction_ledger_revision == "2" * 64
    assert revision.lifecycle_state_revision == "3" * 64
    assert revision.canonicalization_override_revision == "4" * 64
    assert revision.correction_policy_version == "taxonomy-corrections-v1"
    assert revision.matching_policy_version == "legacy-exact-adjacent-gap-v1"
    assert len(revision.effective_hash) == 64


def test_capability_semantics_participate_in_the_profile_projection_revision():
    first = combine_projection_revision("a" * 64, "b" * 64)
    assert len(first) == 64
    assert first == combine_projection_revision("a" * 64, "b" * 64)
    assert first != combine_projection_revision("a" * 64, "c" * 64)
```

- [ ] **Step 2: Run the focused tests and verify the functions are missing**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_capability_graph_adapter.py -v`

Expected: FAIL on imports for `canonical_graph_json`, `graph_revision`, and `build_capability_snapshot`.

- [ ] **Step 3: Implement canonical serialization and hashes**

```python
def canonical_graph_json(graph: CareerCapabilityGraph) -> str:
    payload = graph.model_dump(mode="json", exclude_none=True)
    payload["nodes"] = sorted(payload["nodes"], key=lambda item: item["id"])
    payload["edges"] = sorted(payload["edges"], key=lambda item: item["id"])
    payload["sources"] = sorted(payload["sources"], key=lambda item: item["id"])
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def graph_revision(graph: CareerCapabilityGraph) -> str:
    return hashlib.sha256(canonical_graph_json(graph).encode()).hexdigest()


def combine_projection_revision(
    base_projection_revision: str, effective_hash: str
) -> str:
    return _digest(
        {
            "base_projection_revision": base_projection_revision,
            "effective_hash": effective_hash,
        }
    )
```

The crosswalk hash includes only approved `same_as`, `equivalent_in_context`, and `aligned_to` edges, sorted by edge ID. The Phase 1 value is therefore the deterministic SHA-256 of an empty list, not an absent value.

- [ ] **Step 4: Build the immutable capability snapshot and equality guard**

`build_capability_snapshot` takes the effective map and exact component hashes, calls `cluster_map_to_graph`, validates, derives the legacy projection, and raises `GraphValidationError.single("legacy_projection_mismatch", "legacy projection")` if the projected `ClusterMap` differs from the effective input.

Compute `TaxonomyRevision.effective_hash` from this exact semantic payload:

```python
effective_hash = _digest(
    {
        "base_effective_hash": base_effective_hash,
        "internal_graph_version": internal_graph_version,
        "crosswalk_revision": crosswalk_revision,
        "correction_policy_version": CORRECTION_POLICY_VERSION,
        "matching_policy_version": LEGACY_MATCHING_POLICY_VERSION,
    }
)
```

Do not include component file timestamps, raw lifecycle timestamps, event order, absolute paths, or source attribution prose. Keep raw component hashes in the other revision fields for traceability.

- [ ] **Step 5: Run the full graph-focused test set and lint**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_capability_graph_models.py tests/test_uccm_seeds.py tests/test_capability_graph_validation.py tests/test_capability_graph_adapter.py -v`

Run: `ruff check src/resume_agent/taxonomy/graph_models.py src/resume_agent/taxonomy/uccm_seeds.py src/resume_agent/taxonomy/graph_validation.py src/resume_agent/taxonomy/graph_adapter.py`

Expected: PASS.

- [ ] **Step 6: Commit deterministic revisioning**

```powershell
git add src/resume_agent/taxonomy/graph_adapter.py tests/test_capability_graph_adapter.py
git commit -m "feat(taxonomy): hash deterministic capability snapshots"
```

---

### Task 7: Integrate deployment modes and safe fallback into the single read seam

**Files:**

- Modify: `src/resume_agent/config.py`
- Modify: `src/resume_agent/taxonomy/snapshot.py`
- Modify: `src/resume_agent/profile/effective.py`
- Modify: `tests/test_config.py`
- Modify: `tests/test_profile_effective.py`

**Interfaces:**

- Consumes: `build_capability_snapshot`, `CareerCapabilityMode`, `TaxonomyRevision`, and `EffectiveCapabilitySnapshot`.
- Produces: `Settings.career_capability_mode`, `build_effective_taxonomy(profile_dir, *, corrections_path=None, mode: CareerCapabilityMode | None = None)`, `EffectiveTaxonomy.capability_snapshot`, and manifest fields `capability_mode`, `capability_status`, `capability_error_code`, `capability`.

- [ ] **Step 1: Add settings and mode-behavior tests**

```python
def test_career_capability_mode_defaults_to_legacy(monkeypatch):
    monkeypatch.delenv("CAREER_CAPABILITY_MODE", raising=False)
    assert _settings(env_file=None).career_capability_mode == "legacy"


def test_career_capability_mode_accepts_only_three_states(monkeypatch):
    from pydantic import ValidationError

    monkeypatch.setenv("CAREER_CAPABILITY_MODE", "shadow")
    assert _settings(env_file=None).career_capability_mode == "shadow"
    monkeypatch.setenv("CAREER_CAPABILITY_MODE", "enabled")
    with pytest.raises(ValidationError):
        _settings(env_file=None)
```

Add these tests to `tests/test_profile_effective.py` using its existing `_write` fixture:

```python
def test_modes_keep_the_legacy_projection_stable(tmp_path):
    profile_dir, corrections_path = _write(
        tmp_path,
        aliases={"py": "python"},
        corrections=TaxonomyCorrections(aliases={"js": "javascript"}),
    )
    legacy = build_effective_taxonomy(
        profile_dir, corrections_path=corrections_path, mode="legacy"
    )
    shadow = build_effective_taxonomy(
        profile_dir, corrections_path=corrections_path, mode="shadow"
    )
    uccm = build_effective_taxonomy(
        profile_dir, corrections_path=corrections_path, mode="uccm"
    )
    assert legacy.cluster_map == shadow.cluster_map == uccm.cluster_map
    assert legacy.capability_snapshot is None
    assert shadow.capability_snapshot is not None
    assert uccm.capability_snapshot is not None
    assert legacy.manifest.capability_status == "disabled"
    assert shadow.manifest.capability_status == "shadow"
    assert uccm.manifest.capability_status == "active"


def test_uccm_validation_failure_falls_back_without_changing_the_map(
    monkeypatch, tmp_path
):
    from resume_agent.profile import effective as effective_module
    from resume_agent.taxonomy.graph_validation import GraphValidationError

    profile_dir, corrections_path = _write(tmp_path, aliases={"py": "python"})
    legacy = build_effective_taxonomy(
        profile_dir, corrections_path=corrections_path, mode="legacy"
    )

    def reject(*args, **kwargs):
        raise GraphValidationError.single("invalid_graph", "test rejection")

    monkeypatch.setattr(effective_module, "build_capability_snapshot", reject)
    fallback = build_effective_taxonomy(
        profile_dir, corrections_path=corrections_path, mode="uccm"
    )
    assert fallback.cluster_map == legacy.cluster_map
    assert fallback.semantic_revision == legacy.semantic_revision
    assert fallback.capability_snapshot is None
    assert fallback.manifest.capability_status == "fallback"
    assert fallback.manifest.capability_error_code == "invalid_graph"
```

- [ ] **Step 2: Run tests and verify failures on missing settings/signatures**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_config.py tests/test_profile_effective.py -v`

Expected: FAIL because `career_capability_mode`, `mode`, and capability manifest fields do not exist.

- [ ] **Step 3: Add the one deployment setting**

In `Settings`:

```python
    career_capability_mode: Literal["legacy", "shadow", "uccm"] = "legacy"
```

No second flag is permitted.

- [ ] **Step 4: Extend the frozen snapshot and compatibility manifest**

In `taxonomy/snapshot.py`, add these fields without changing existing defaults or precedence:

```python
@dataclass(frozen=True)
class TaxonomyManifest:
    generated: str = ""
    corrections: str = ""
    state: str = ""
    overrides: str = ""
    semantic: str = ""
    capability_mode: CareerCapabilityMode = "legacy"
    capability_status: Literal["disabled", "shadow", "active", "fallback"] = (
        "disabled"
    )
    capability_error_code: str | None = None
    capability: TaxonomyRevision | None = None


@dataclass(frozen=True)
class EffectiveTaxonomy:
    cluster_map: ClusterMap
    capability_snapshot: EffectiveCapabilitySnapshot | None = None
```

Retain every existing `EffectiveTaxonomy` field after `cluster_map`; the excerpt only shows the new field position. Existing constructors continue to work because the new field has a default.

- [ ] **Step 5: Select the mode only inside `build_effective_taxonomy`**

Change the signature to:

```python
def build_effective_taxonomy(
    profile_dir: str | Path,
    *,
    corrections_path: str | Path | None = None,
    mode: CareerCapabilityMode | None = None,
) -> EffectiveTaxonomy:
```

Resolve `requested_mode = mode or get_settings().career_capability_mode`. Always build the Phase 0 `resolved` object first. Always create a complete `TaxonomyRevision`; legacy mode uses an empty `internal_graph_version`, empty external sources, the deterministic empty crosswalk hash, existing component hashes, current policy versions, and the existing semantic hash.

For `shadow` and `uccm`, call `build_capability_snapshot` with `snapshot.generated`, `snapshot.corrections`, `overrides`, and all component hashes. Use this exact activation rule:

```python
active_map = (
    capability.legacy_projection if requested_mode == "uccm" else resolved.cluster_map
)
status = "active" if requested_mode == "uccm" else "shadow"
return replace(
    resolved,
    cluster_map=active_map,
    capability_snapshot=capability,
    semantic_revision=capability.revision.effective_hash,
    projection_revision=combine_projection_revision(
        resolved.projection_revision,
        capability.revision.effective_hash,
    ),
    manifest=replace(
        base_manifest,
        semantic=capability.revision.effective_hash,
        capability_mode=requested_mode,
        capability_status=status,
        capability=capability.revision,
    ),
)
```

Catch only `GraphValidationError`; projection mismatch already uses that type with code `legacy_projection_mismatch`. Log the exception internally, then return the Phase 0 object with its original map/revisions, `capability_snapshot=None`, `capability_status="fallback"`, and the first stable issue code. Do not catch `OSError`, database failures, or arbitrary programming exceptions.

- [ ] **Step 6: Run Phase 0 and Phase 1 seam tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_config.py tests/test_profile_effective.py tests/test_taxonomy_snapshot.py tests/test_effective_taxonomy_seam.py tests/test_capability_graph_seam.py -v`

Expected: all existing tests PASS; the Phase 1 acceptance test becomes XPASS and therefore fails strictly. Keep the marker until Task 9.

- [ ] **Step 7: Lint and commit mode integration**

Run: `ruff check src/resume_agent/config.py src/resume_agent/taxonomy/snapshot.py src/resume_agent/profile/effective.py tests/test_config.py tests/test_profile_effective.py`

```powershell
git add src/resume_agent/config.py src/resume_agent/taxonomy/snapshot.py src/resume_agent/profile/effective.py tests/test_config.py tests/test_profile_effective.py
git commit -m "feat(taxonomy): add reversible UCCM graph deployment modes"
```

---

### Task 8: Persist and expose the complete revision additively

**Files:**

- Modify: `src/resume_agent/profile/matrix.py`
- Modify: `src/resume_agent/api/schemas/match_gap.py`
- Modify: `tests/test_profile_matrix.py`
- Modify: `tests/test_tailor_service.py`
- Modify: `tests/api/test_match_gap.py`
- Modify: `tests/api/test_schemas_match_gap.py`
- Regenerate: `contracts/openapi.json`
- Regenerate: `contracts/ts/api.ts`
- Regenerate: `web/src/lib/api/schema.ts`

**Interfaces:**

- Consumes: nested `TaxonomyRevision` in `TaxonomyManifest` and existing `asdict(taxonomy.manifest)` write paths.
- Produces: `SourceSnapshotRevisionModel`, `TaxonomyRevisionModel`, `SourceSnapshotRevisionOut`, and `TaxonomyRevisionOut`; no new endpoint and no changed existing field.

- [ ] **Step 1: Add serialization and legacy-payload-invariance tests**

In `tests/test_profile_matrix.py`, build a taxonomy in `uccm` mode and assert:

```python
assert matrix.taxonomy_manifest is not None
assert matrix.taxonomy_manifest.capability is not None
assert matrix.taxonomy_manifest.capability.effective_hash == matrix.taxonomy_revision
assert matrix.taxonomy_manifest.capability.internal_graph_version
```

In `tests/test_tailor_service.py`, keep its existing persisted revision assertions and add:

```python
manifest = versions[0].taxonomy_manifest_json
assert manifest is not None
assert manifest["capability"]["effective_hash"] == versions[0].taxonomy_revision
assert manifest["capability_mode"] == "uccm"
```

In `tests/api/test_match_gap.py`, run the existing projection fixture once with `legacy` and once with `uccm` by monkeypatching `resume_agent.profile.effective.get_settings`. Remove `taxonomyRevision` and `taxonomyManifest` before comparing; every remaining byte of the JSON payload must be equal. Then assert the UCCM manifest contains `capabilityStatus="active"` and a 64-character `capability.internalGraphVersion`.

- [ ] **Step 2: Run focused tests and verify nested models are rejected or dropped**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_profile_matrix.py tests/test_tailor_service.py tests/api/test_match_gap.py tests/api/test_schemas_match_gap.py -v`

Expected: FAIL because the Pydantic compatibility projections do not yet declare the nested fields.

- [ ] **Step 3: Add matching matrix and API projection models**

Add the same field names on both the `ExtensibleModel` persistence side and `CamelModel` API side:

```python
class SourceSnapshotRevisionModel(ExtensibleModel):
    namespace: str
    version: str
    checksum: str


class TaxonomyRevisionModel(ExtensibleModel):
    internal_graph_version: str = ""
    external_source_snapshots: list[SourceSnapshotRevisionModel] = Field(
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


class TaxonomyManifestModel(ExtensibleModel):
    generated: str = ""
    corrections: str = ""
    state: str = ""
    overrides: str = ""
    semantic: str = ""
    capability_mode: Literal["legacy", "shadow", "uccm"] = "legacy"
    capability_status: Literal["disabled", "shadow", "active", "fallback"] = (
        "disabled"
    )
    capability_error_code: str | None = None
    capability: TaxonomyRevisionModel | None = None
```

Mirror them as `SourceSnapshotRevisionOut`, `TaxonomyRevisionOut`, and added fields on `TaxonomyManifestOut`; `CamelModel` produces `internalGraphVersion`, `capabilityMode`, and the other camelCase wire keys. Do not add graph nodes, edges, correction events, or source content to the API in this phase.

- [ ] **Step 4: Verify matrix, resume version, and API compatibility**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_profile_matrix.py tests/test_tailor_service.py tests/api/test_match_gap.py tests/api/test_schemas_match_gap.py -v`

Expected: PASS. The legacy and UCCM payloads differ only in taxonomy revision metadata.

- [ ] **Step 5: Regenerate OpenAPI and TypeScript contracts using the Windows-safe commands**

```powershell
.\.venv\Scripts\python.exe scripts\export_openapi.py
npx.cmd --yes openapi-typescript contracts\openapi.json -o contracts\ts\api.ts
Copy-Item -LiteralPath contracts\ts\api.ts -Destination web\src\lib\api\schema.ts
```

If `bash scripts/gen_ts_client.sh` already works in the execution environment, it is equivalent. Inspect the diff and keep only semantic contract changes, not line-ending churn.

- [ ] **Step 6: Run contract drift and frontend type gates**

Run: `.\.venv\Scripts\python.exe -m pytest tests/api/test_openapi_contract.py -v`

Run: `npm.cmd --prefix web run test:run`

Run: `npm.cmd --prefix web run build`

Expected: PASS. Generated schemas add nested optional revision metadata; existing match-gap fields remain unchanged.

- [ ] **Step 7: Commit persistence and generated contracts together**

```powershell
git add src/resume_agent/profile/matrix.py src/resume_agent/api/schemas/match_gap.py tests/test_profile_matrix.py tests/test_tailor_service.py tests/api/test_match_gap.py tests/api/test_schemas_match_gap.py contracts/openapi.json contracts/ts/api.ts web/src/lib/api/schema.ts
git commit -m "feat(api): expose complete capability taxonomy revision"
```

---

### Task 9: Migration note, acceptance activation, rollback proof, and final verification

**Files:**

- Create: `docs/notes/2026-08-19-uccm-phase1-graph-adapter-migration.md`
- Modify: `tests/test_capability_graph_seam.py`
- Test: complete backend and frontend gates

**Interfaces:**

- Consumes: every Phase 1 task.
- Produces: a green phase acceptance test and an operator-readable rollback contract.

- [ ] **Step 1: Write the migration note with exact operational behavior**

The note must contain these concrete sections and values:

```markdown
# UCCM Phase 1 Graph Adapter Migration

## Persisted data

Phase 1 writes no graph artifact. Existing `cluster_map.json`, correction ledger,
taxonomy state, profile overrides, matrices, and resume versions remain readable.
New matrices and resume versions add a nested capability revision to the existing
taxonomy manifest.

## Modes

- `CAREER_CAPABILITY_MODE=legacy` (default): Phase 0 behavior; no graph build.
- `CAREER_CAPABILITY_MODE=shadow`: build and validate the graph, serve the Phase 0 map.
- `CAREER_CAPABILITY_MODE=uccm`: serve the graph-derived legacy projection after exact equality validation.

All three modes use the current exact/adjacent/gap matcher. Phase 1 does not change
ranking, suggestions, tailoring, or candidate claims.

## Rollback

Set `CAREER_CAPABILITY_MODE=legacy` and restart the API and workers. No data deletion,
backfill, or schema downgrade is required. Nested revision metadata remains historical
provenance and is safe for older readers because the surrounding models are additive.

## Failure behavior

Graph validation or projection mismatch returns the Phase 0 map, preserves the Phase 0
semantic revision, and records `capabilityStatus=fallback` plus a stable error code.
No fallback writes or rewrites taxonomy inputs.

## Data retained after rollback

Existing taxonomy files, correction events projected in historical snapshots, matrix
manifests, and resume-version manifests remain. No graph database or graph JSON file
exists to clean up.
```

- [ ] **Step 2: Remove the strict xfail marker from the acceptance test**

Delete only the `@pytest.mark.xfail` decorator and its arguments. Keep every assertion intact.

- [ ] **Step 3: Run the phase acceptance and rollback-focused tests**

Run: `.\.venv\Scripts\python.exe -m pytest tests/test_capability_graph_seam.py tests/test_profile_effective.py tests/api/test_match_gap.py -v`

Expected: PASS with no xfail or xpass.

- [ ] **Step 4: Run the full backend test suite and lint**

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Run: `ruff check src tests evals`

Expected: PASS. A timeout or aborted suite is incomplete verification.

- [ ] **Step 5: Run all frontend gates and repository hygiene checks**

Run: `npm.cmd --prefix web run test:run`

Run: `npm.cmd --prefix web run lint`

Run: `npm.cmd --prefix web run build`

Run: `git diff --check`

Expected: PASS, with no contract drift and no whitespace errors.

- [ ] **Step 6: Review the final diff against the phase boundary**

Verify that the diff contains no profile assertions, typed job requirements, graph traversal for matching, UCCM page/component work, external source records, imported framework wording, database graph tables, or modifications to the exact/adjacent/gap decision code.

- [ ] **Step 7: Commit the migration note and activated acceptance test**

```powershell
git add docs/notes/2026-08-19-uccm-phase1-graph-adapter-migration.md tests/test_capability_graph_seam.py
git commit -m "docs(taxonomy): document UCCM graph-adapter migration and rollback"
```

---

## Self-Review

**Spec coverage.** Task 2 defines every required concept and edge type plus source, correction, revision, and effective-snapshot models. Task 3 seeds all six layers, eight original career-core families, and twelve transferable work functions. Tasks 4–6 enforce stable namespaced identity, typed edge direction/signatures, source metadata, deterministic serialization, alias/hierarchy cycle rejection, correction replay, exact legacy round-trip, and complete revision hashing. Task 7 extends the Phase 0 seam and implements the required `legacy`/`shadow`/`uccm` rollback modes. Task 8 preserves matrix, resume-version, API, OpenAPI, and frontend compatibility. Task 9 documents rollback and proves that current matching and stored artifacts remain readable.

**Correctness reconciliation.** The design sequence says term typing follows graph primitives. Therefore legacy canonical strings are marked `legacy_placeholder`; assigning them governed semantic types in this phase would collapse Phase 1 and Phase 2. Learned domains/categories remain `LegacyProjectionMetadata`, so the adapter cannot accidentally create same-domain semantic or transfer edges. The graph is derived inside the one Phase 0 read seam, avoiding a second taxonomy loader or a write-on-read cache.

**Revision consistency.** `TaxonomyRevision.effective_hash` is used identically by `EffectiveCapabilitySnapshot`, `EffectiveTaxonomy.semantic_revision`, the manifest's legacy `semantic` field, new matrices, match-gap responses, and new resume versions. Component hashes remain trace metadata, preserving Phase 0's rule that semantically identical effective content does not cause cache churn.

**Rollback consistency.** `legacy` never builds the graph; `shadow` never serves its projection; `uccm` serves it only after exact equality. Both graph rejection paths preserve the Phase 0 map and semantic revision. Since Phase 1 persists no graph store, rollback requires only one environment setting and a process restart.

**Placeholder scan.** Every task names exact files, interfaces, tests, commands, expected results, and commit boundaries. Every new enum, seed row, mode, policy version, source field, revision field, fallback status, and compatibility assertion is defined before later tasks consume it.

**Type consistency.** `CareerCapabilityGraph`, `CorrectionEvent`, `TaxonomyRevision`, `EffectiveCapabilitySnapshot`, `canonical_graph_json`, `graph_revision`, `cluster_map_to_graph`, `graph_to_cluster_map`, `build_capability_snapshot`, `capability_snapshot`, `capability_mode`, `capability_status`, and `capability_error_code` keep the same names and meanings across tasks.
