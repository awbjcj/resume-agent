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
    GraphValidationIssue,
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


def _graph(nodes, edges=(), *, sources=None, legacy_projection=None):
    return CareerCapabilityGraph(
        model_version="0.1.0-design",
        nodes=list(nodes),
        edges=list(edges),
        sources=list(sources) if sources is not None else [_source()],
        legacy_projection=legacy_projection or LegacyProjectionMetadata(),
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


def test_errors_are_stably_sorted_and_single_is_a_usable_fallback():
    error = GraphValidationError(
        [
            GraphValidationIssue("z_code", "a"),
            GraphValidationIssue("a_code", "z"),
        ]
    )
    assert error.issues == (
        GraphValidationIssue("a_code", "z"),
        GraphValidationIssue("z_code", "a"),
    )
    assert GraphValidationError.single("invalid_graph", "test").issues == (
        GraphValidationIssue("invalid_graph", "test"),
    )


def test_hierarchy_direction_and_scope_invariants_are_rejected():
    nodes = [_node("legacy:skill:a"), _node("legacy:skill:b")]
    edges = [
        ConceptEdge(
            id="edge:broader",
            subject_id="legacy:skill:a",
            predicate="broader_than",
            object_id="legacy:skill:b",
            revision_created="r1",
            source_refs=["source:internal:test:1"],
        ),
        ConceptEdge(
            id="edge:narrower",
            subject_id="legacy:skill:a",
            predicate="narrower_than",
            object_id="legacy:skill:b",
            revision_created="r1",
            source_refs=["source:internal:test:1"],
        ),
        ConceptEdge(
            id="edge:same-as",
            subject_id="legacy:skill:a",
            predicate="same_as",
            object_id="legacy:skill:b",
            revision_created="r1",
            source_refs=["source:internal:test:1"],
        ),
        ConceptEdge(
            id="edge:profile",
            subject_id="legacy:skill:a",
            predicate="aligned_to",
            object_id="legacy:skill:b",
            revision_created="r1",
            source_refs=["source:internal:test:1"],
            scope="profile",
        ),
    ]
    with pytest.raises(GraphValidationError) as exc:
        validate_capability_graph(_graph(nodes, edges))
    assert {issue.code for issue in exc.value.issues} >= {
        "hierarchy_cycle",
        "invalid_edge_direction",
        "invalid_edge_scope",
    }


def test_matching_local_sources_are_valid_and_cannot_back_global_edges():
    workspace_source = _source().model_copy(
        update={
            "id": "source:legacy-cluster-map:test",
            "namespace": "legacy_cluster_map",
            "tenant_scope": "workspace",
        }
    )
    profile_source = _source().model_copy(
        update={
            "id": "source:profile-overrides:test",
            "namespace": "profile_overrides",
            "tenant_scope": "profile",
        }
    )
    first = _node("legacy:skill:a").model_copy(
        update={"source_refs": [workspace_source.id]}
    )
    second = _node("legacy:skill:b").model_copy(
        update={"source_refs": [profile_source.id]}
    )
    tenant_edge = ConceptEdge(
        id="edge:tenant",
        subject_id=first.id,
        predicate="aligned_to",
        object_id=second.id,
        revision_created="r1",
        source_refs=[workspace_source.id],
        scope="tenant",
    )
    profile_edge = ConceptEdge(
        id="edge:profile",
        subject_id=second.id,
        predicate="aligned_to",
        object_id=first.id,
        revision_created="r1",
        source_refs=[profile_source.id],
        scope="profile",
    )
    validate_capability_graph(
        _graph(
            [first, second],
            [tenant_edge, profile_edge],
            sources=[workspace_source, profile_source],
        )
    )

    global_edge = tenant_edge.model_copy(
        update={"id": "edge:global", "scope": "global"}
    )
    second_with_workspace_source = second.model_copy(
        update={"source_refs": [workspace_source.id]}
    )
    with pytest.raises(GraphValidationError) as exc:
        validate_capability_graph(
            _graph(
                [first, second_with_workspace_source],
                [global_edge],
                sources=[workspace_source],
            )
        )
    assert "invalid_edge_scope" in {issue.code for issue in exc.value.issues}


def test_external_provenance_and_legacy_projection_invariants_are_checked():
    node = _node("legacy:skill:a")
    external = SourceManifest(
        id="source:external:test:1",
        namespace="external",
        source_id="test",
        source_version="",
        source_uri="",
        license_id="",
        attribution="",
        checksum="c" * 64,
        mapping_status="mapped",
        tenant_scope="global",
    )
    projection = LegacyProjectionMetadata(
        concept_tokens={node.id: "a", "legacy:skill:missing": "missing"},
        domain_of={node.id: "web"},
        domain_label={"unknown": "Unknown"},
        category_of={"unknown": "not-a-category"},
    )
    with pytest.raises(GraphValidationError) as exc:
        validate_capability_graph(
            _graph([node], sources=[external], legacy_projection=projection)
        )
    assert {issue.code for issue in exc.value.issues} >= {
        "missing_external_source_version",
        "missing_external_source_uri",
        "missing_external_source_license",
        "missing_external_source_attribution",
        "dangling_legacy_concept",
        "unprojected_legacy_domain_label",
        "unprojected_legacy_category",
        "invalid_legacy_category",
    }


def test_missing_domain_label_is_valid_when_projection_domain_exists():
    node = _node("legacy:skill:a")
    projection = LegacyProjectionMetadata(
        concept_tokens={node.id: "a"},
        domain_of={node.id: "web"},
        category_of={"web": "frontend-web"},
    )
    validate_capability_graph(_graph([node], legacy_projection=projection))
