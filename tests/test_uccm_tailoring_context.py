from __future__ import annotations

import pytest

from resume_agent.matching.engine import shadow_match_requirement
from resume_agent.models.requirements import JobRequirement
from resume_agent.profile.assertions import CapabilityAssertion, LegacyAssertionProjection
from resume_agent.profile.matrix import SkillMatrix
from resume_agent.taxonomy.graph_models import CareerCapabilityGraph, ConceptEdge, EdgeType


def _assertion(concept_id: str, display: str) -> CapabilityAssertion:
    return CapabilityAssertion(
        id=f"assertion:{concept_id}",
        subject_id="profile:current",
        concept_id=concept_id,
        concept_type="capability",
        term_decision_id=f"term:{concept_id}",
        assertion_status="evidenced",
        evidence_fact_ids=[f"fact:{concept_id}"],
        proficiency_level=3,
        evidence_confidence=0.95,
        usage_count=1,
        claimability="literal_evidenced",
        facts_revision="facts-v1",
        taxonomy_revision="tax-v1",
        term_typing_policy_revision="term-typing-v1",
        legacy_projection=LegacyAssertionProjection(
            key=concept_id,
            display=display,
            category="hard",
            strength=0.9,
        ),
    )


def _requirement(concept_id: str, label: str, order: int = 0) -> JobRequirement:
    return JobRequirement(
        id=f"requirement:{concept_id}",
        job_id="42",
        source_text=label,
        provenance="legacy_list_item",
        parsed_concept_id=concept_id,
        parsed_concept_label=label,
        concept_type="capability",
        requirement_kind="must_have",
        strictness="capability",
        importance=1.0,
        evidence_expectation="candidate_evidence",
        extraction_confidence=1.0,
        taxonomy_revision="tax-v1",
        term_decision_id=f"term:{concept_id}",
        legacy_source="must",
        legacy_order=order,
    )


def _edge(subject: str, predicate: EdgeType, object_: str) -> ConceptEdge:
    return ConceptEdge(
        id=f"edge:{subject}:{predicate}:{object_}",
        subject_id=subject,
        predicate=predicate,
        object_id=object_,
        confidence=1.0,
        status="approved",
        scope="global",
        source_refs=["source:test"],
        revision_created="tax-v1",
    )


def test_context_pins_revisions_and_derives_legacy_projection_without_renaming_transfer():
    from resume_agent.tailor.context import (
        build_uccm_tailoring_context,
        project_legacy_skill_context,
    )

    exact = _assertion("python", "Python")
    transferable = _assertion("program-leadership", "Program leadership")
    matrix = SkillMatrix(
        facts_sha256="facts-v1",
        taxonomy_revision="tax-v1",
        assertion_policy_revision="profile-assertions-v1",
        assertions=[exact, transferable],
    )
    exact_requirement = _requirement("python", "Python")
    target_requirement = _requirement("kubernetes", "Kubernetes", 1)
    graph = CareerCapabilityGraph(
        model_version="test",
        edges=[_edge("program-leadership", "transferable_to", "kubernetes")],
    )
    results = [
        shadow_match_requirement(exact_requirement, matrix.assertions, graph, legacy_coverage="covered"),
        shadow_match_requirement(target_requirement, matrix.assertions, graph, legacy_coverage="gap"),
    ]

    context = build_uccm_tailoring_context(
        matrix=matrix,
        requirements=[exact_requirement, target_requirement],
        shadow_results=results,
    )
    legacy = project_legacy_skill_context(context)

    assert context.taxonomy_revision == "tax-v1"
    assert context.facts_revision == "facts-v1"
    assert context.assertion_policy_revision == "profile-assertions-v1"
    assert context.matching_policy_revision == "uccm-match-v1"
    assert context.requirement_ids == ["requirement:python", "requirement:kubernetes"]
    assert context.assertion_ids == ["assertion:python", "assertion:program-leadership"]
    assert [(item.coverage, item.row.display if item.row else None) for item in legacy.matches] == [
        ("covered", "Python"),
        ("adjacent", "Program leadership"),
    ]
    assert all(item.row is None or item.row.display != "Kubernetes" for item in legacy.matches[1:])


def test_context_rejects_mixed_artifact_revisions():
    from resume_agent.tailor.context import build_uccm_tailoring_context

    assertion = _assertion("python", "Python")
    matrix = SkillMatrix(
        facts_sha256="facts-v1",
        taxonomy_revision="tax-v1",
        assertion_policy_revision="profile-assertions-v1",
        assertions=[assertion],
    )
    requirement = _requirement("python", "Python").model_copy(
        update={"taxonomy_revision": "tax-v2"}
    )
    result = shadow_match_requirement(
        requirement,
        [assertion],
        CareerCapabilityGraph(model_version="test"),
        legacy_coverage="covered",
    )

    with pytest.raises(ValueError, match="taxonomy revision"):
        build_uccm_tailoring_context(
            matrix=matrix,
            requirements=[requirement],
            shadow_results=[result],
        )
