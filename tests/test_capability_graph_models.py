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
        ConceptNode.model_validate(
            {
                "id": "internal:bad:x",
                "type": "mystery",
                "preferred_label": "X",
                "normalized_label": "x",
                "source_refs": ["source:internal:test:1"],
            }
        )
    with pytest.raises(ValidationError) as error_info:
        ConceptEdge.model_validate(
            {
                "id": "edge:bad",
                "subject_id": "internal:skill:a",
                "predicate": "looks_like",
                "object_id": "internal:skill:b",
                "source_refs": ["source:internal:test:1"],
                "revision_created": "revision:test:1",
            }
        )
    assert any(
        error["loc"] == ("predicate",) for error in error_info.value.errors()
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
