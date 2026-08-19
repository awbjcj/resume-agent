from __future__ import annotations

import pytest

from resume_agent.profile.matrix import Overrides
from resume_agent.taxonomy.clusters import ClusterMap
from resume_agent.taxonomy.corrections import TaxonomyCorrections
from resume_agent.taxonomy.graph_models import ConceptEdge
from resume_agent.taxonomy.graph_adapter import (
    cluster_map_to_graph,
    graph_to_cluster_map,
    legacy_concept_id,
)
from resume_agent.taxonomy.uccm_seeds import UCCM_SOURCE

GENERATED_REVISION = "1" * 64
CORRECTION_REVISION = "2" * 64
OVERRIDE_REVISION = "3" * 64


def _map() -> ClusterMap:
    return ClusterMap(
        aliases={"js": "javascript", "python": "python", "reactjs": "react"},
        domain_of={
            "javascript": "web-langs",
            "python": "scripting",
            "react": "web-frameworks",
        },
        domain_label={
            "scripting": "Scripting",
            "web-langs": "Web Languages",
            "web-frameworks": "Web Frameworks",
        },
        category_of={
            "scripting": "languages",
            "web-langs": "languages",
            "web-frameworks": "frontend-web",
        },
    )


def _graph(cmap: ClusterMap = _map()):
    return cluster_map_to_graph(
        cmap,
        generated_revision=GENERATED_REVISION,
        correction_revision=CORRECTION_REVISION,
        override_revision=OVERRIDE_REVISION,
    )


def test_effective_cluster_map_round_trips_exactly_through_the_graph():
    graph, _ = _graph()

    assert graph_to_cluster_map(graph) == _map()
    assert graph_to_cluster_map(graph).aliases["python"] == "python"
    assert legacy_concept_id("C++") == "legacy:skill:c%2B%2B"


def test_domain_and_category_membership_never_becomes_a_semantic_edge():
    graph, _ = _graph()

    assert {edge.predicate for edge in graph.edges} == {"lexical_alias_of"}
    assert graph.legacy_projection.domain_label["web-langs"] == "Web Languages"
    assert graph.legacy_projection.category_of["web-frameworks"] == "frontend-web"


def test_legacy_nodes_are_explicitly_untyped_placeholders_with_provenance():
    graph, _ = _graph()

    legacy_nodes = [node for node in graph.nodes if node.id.startswith("legacy:")]
    assert legacy_nodes
    assert {node.type for node in legacy_nodes} == {"skill"}
    assert {node.type_assignment_status for node in legacy_nodes} == {
        "legacy_placeholder"
    }
    assert {node.claim_policy for node in legacy_nodes} == {"evidence_required"}
    assert {tuple(node.career_layers) for node in legacy_nodes} == {()}
    assert {tuple(node.source_refs) for node in legacy_nodes} == {
        (f"source:legacy-cluster-map:{GENERATED_REVISION}",)
    }
    assert {len(node.source_mappings) for node in legacy_nodes} == {1}
    python_node = next(node for node in legacy_nodes if node.id == legacy_concept_id("python"))
    mapping = python_node.source_mappings[0]
    assert mapping.source_label == "python"
    assert mapping.source_version == GENERATED_REVISION
    assert mapping.source_uri == "workspace://profile/cluster_map.json"
    assert mapping.license_id == "workspace-private"
    assert mapping.import_checksum == GENERATED_REVISION


def test_governed_seed_nodes_do_not_leak_into_the_legacy_projection():
    graph, _ = _graph()

    governed_nodes = [
        node for node in graph.nodes if node.type_assignment_status == "governed"
    ]
    assert len(governed_nodes) == 20
    assert all(node.id not in graph.legacy_projection.concept_tokens for node in governed_nodes)
    assert all(node.source_refs == [UCCM_SOURCE.id] for node in governed_nodes)


def test_correction_and_profile_override_events_are_stable_and_complete():
    corrections = TaxonomyCorrections(
        aliases={"reactjs": "react"},
        added_skills=["graphql"],
        removed_skills=["coffee"],
        skill_domain={"graphql": "web-frameworks"},
        domain_renames={"web-frameworks": "Web UI Frameworks"},
        domain_merges={"old-web": "web-frameworks"},
        domain_category={"web-frameworks": "frontend-web"},
    )
    overrides = Overrides(
        alias={"js": "javascript"},
        forbid_alias=[["js", "javascript"]],
        ban=["coffee"],
        category={"graphql": "frontend-web"},
        group={"react": "frontend-web"},
    )

    first_graph, first_events = cluster_map_to_graph(
        _map(),
        generated_revision=GENERATED_REVISION,
        correction_revision=CORRECTION_REVISION,
        override_revision=OVERRIDE_REVISION,
        corrections=corrections,
        overrides=overrides,
    )
    second_graph, second_events = cluster_map_to_graph(
        _map(),
        generated_revision=GENERATED_REVISION,
        correction_revision=CORRECTION_REVISION,
        override_revision=OVERRIDE_REVISION,
        corrections=corrections,
        overrides=overrides,
    )

    assert first_events == second_events
    assert first_graph == second_graph
    assert first_events == tuple(sorted(first_events, key=lambda event: event.id))
    assert {event.scope for event in first_events} == {"tenant", "profile"}
    assert {event.operation for event in first_events} == {
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
    }


def test_profile_alias_provenance_precedes_correction_and_generated_sources():
    graph, _ = cluster_map_to_graph(
        _map(),
        generated_revision=GENERATED_REVISION,
        correction_revision=CORRECTION_REVISION,
        override_revision=OVERRIDE_REVISION,
        corrections=TaxonomyCorrections(aliases={"js": "javascript"}),
        overrides=Overrides(alias={"js": "javascript"}),
    )

    js_edge = next(
        edge for edge in graph.edges if edge.subject_id == legacy_concept_id("js")
    )
    assert js_edge.source_refs == [f"source:profile-overrides:{OVERRIDE_REVISION}"]
    assert js_edge.scope == "profile"
    assert js_edge.revision_created == OVERRIDE_REVISION
    assert [source.id for source in graph.sources] == sorted(
        source.id for source in graph.sources
    )


def test_reverse_projection_flattens_nonself_alias_chains_and_preserves_self_aliases():
    graph, _ = _graph(
        ClusterMap(aliases={"a": "b", "b": "c", "python": "python"})
    )

    assert graph_to_cluster_map(graph) == ClusterMap(
        aliases={"a": "c", "b": "c", "python": "python"}
    )


def test_reverse_projection_rejects_multinode_cycles_and_ignores_nonlexical_edges():
    graph, _ = _graph(ClusterMap(aliases={"a": "b", "b": "b"}))
    semantic_edge = ConceptEdge(
        id="edge:ignored-semantic-edge",
        subject_id=legacy_concept_id("a"),
        predicate="same_as",
        object_id=legacy_concept_id("b"),
        direction="bidirectional",
        source_refs=[UCCM_SOURCE.id],
        revision_created="test",
    )
    nonsemantic_graph = graph.model_copy(update={"edges": [*graph.edges, semantic_edge]})
    assert graph_to_cluster_map(nonsemantic_graph).aliases == {"a": "b", "b": "b"}

    cyclic_edges = [
        edge.model_copy(update={"object_id": legacy_concept_id("a")})
        if edge.subject_id == legacy_concept_id("b")
        else edge
        for edge in graph.edges
    ]
    cyclic_graph = graph.model_copy(update={"edges": cyclic_edges})
    with pytest.raises(ValueError, match="alias cycle"):
        graph_to_cluster_map(cyclic_graph)
