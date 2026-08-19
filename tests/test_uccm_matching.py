from __future__ import annotations

import pytest

from resume_agent.models.requirements import JobRequirement, RequirementStrictness
from resume_agent.profile.assertions import (
    CapabilityAssertion,
    LegacyAssertionProjection,
)
from resume_agent.taxonomy.graph_models import CareerCapabilityGraph, ConceptEdge, EdgeType
from resume_agent.taxonomy.term_typing import TermConceptType


def _requirement(
    concept_id: str | None,
    *,
    concept_type: TermConceptType = "capability",
    strictness: RequirementStrictness = "capability",
    minimum_proficiency=None,
    context=None,
    recency_constraint=None,
    requirement_kind=None,
    source_text="Target Capability",
    parsed_concept_label="target capability",
    exact_non_substitutable=None,
):
    return JobRequirement(
        id=f"req:{concept_id or 'unknown'}:{strictness}",
        job_id="42",
        source_text=source_text,
        provenance="legacy_list_item",
        parsed_concept_id=concept_id,
        parsed_concept_label=parsed_concept_label,
        concept_type=concept_type,
        requirement_kind=requirement_kind
        or ("credential_required" if concept_type == "credential" else "must_have"),
        strictness=strictness,
        minimum_proficiency=minimum_proficiency,
        context=context or {},
        importance=1.0,
        evidence_expectation=(
            "verified_fact" if concept_type == "credential" else "candidate_evidence"
        ),
        recency_constraint=recency_constraint,
        extraction_confidence=1.0,
        taxonomy_revision="tax-v1",
        term_decision_id="term:1",
        legacy_source="must",
        legacy_order=0,
        exact_non_substitutable=(
            strictness in {"credential", "exact_product"}
            if exact_non_substitutable is None
            else exact_non_substitutable
        ),
    )


def _assertion(
    concept_id: str,
    *,
    concept_type: TermConceptType = "capability",
    proficiency_level=None,
    context=None,
    last_used="current",
    evidenced=True,
):
    return CapabilityAssertion(
        id=f"assertion:{concept_id}",
        subject_id="profile:current",
        concept_id=concept_id,
        concept_type=concept_type,
        term_decision_id="term:profile",
        assertion_status="evidenced" if evidenced else "self_reported",
        evidence_fact_ids=["fact:1"] if evidenced else [],
        context=context,
        proficiency_level=proficiency_level,
        evidence_confidence=1.0 if evidenced else None,
        last_used=last_used,
        usage_count=1 if evidenced else 0,
        claimability=("literal_evidenced" if evidenced else "self_reported_unverified"),
        facts_revision="facts-v1",
        taxonomy_revision="tax-v1",
        term_typing_policy_revision="term-typing-v1",
        legacy_projection=LegacyAssertionProjection(
            key=concept_id,
            display=f"Candidate {concept_id}",
            strength=1.0,
        ),
    )


def _edge(subject: str, predicate: EdgeType, object_: str, **overrides):
    return ConceptEdge(
        id=f"edge:{subject}:{predicate}:{object_}",
        subject_id=subject,
        predicate=predicate,
        object_id=object_,
        confidence=overrides.pop("confidence", 1.0),
        status=overrides.pop("status", "approved"),
        scope=overrides.pop("scope", "global"),
        source_refs=["source:test"],
        revision_created="tax-v1",
        **overrides,
    )


def _graph(*edges: ConceptEdge) -> CareerCapabilityGraph:
    return CareerCapabilityGraph(model_version="test", edges=list(edges))


@pytest.mark.parametrize(
    ("requirement", "assertions", "graph", "expected"),
    [
        (_requirement("same"), [_assertion("same")], _graph(), "verified_exact"),
        (
            _requirement("target"),
            [_assertion("candidate")],
            _graph(_edge("candidate", "same_as", "target")),
            "verified_equivalent",
        ),
        (
            _requirement("target"),
            [_assertion("candidate")],
            _graph(_edge("candidate", "broader_than", "target")),
            "covered_broader",
        ),
        (
            _requirement("target"),
            [_assertion("candidate")],
            _graph(_edge("candidate", "narrower_than", "target")),
            "covered_narrower",
        ),
        (
            _requirement("target"),
            [_assertion("candidate")],
            _graph(_edge("candidate", "transferable_to", "target")),
            "transferable",
        ),
        (
            _requirement("target"),
            [_assertion("candidate")],
            _graph(_edge("candidate", "prerequisite_for", "target")),
            "partial",
        ),
        (
            _requirement("same", minimum_proficiency=4),
            [_assertion("same", proficiency_level=2)],
            _graph(),
            "level_gap",
        ),
        (
            _requirement("same", context={"industry": "finance"}),
            [_assertion("same", context="healthcare")],
            _graph(),
            "context_gap",
        ),
        (
            _requirement("same", recency_constraint="2025"),
            [_assertion("same", last_used="2020")],
            _graph(),
            "recency_gap",
        ),
        (
            _requirement("same"),
            [_assertion("same", evidenced=False)],
            _graph(),
            "evidence_gap",
        ),
        (
            _requirement("tool", concept_type="tool_technology", strictness="exact_product"),
            [],
            _graph(),
            "tool_gap",
        ),
        (
            _requirement("credential", concept_type="credential", strictness="credential"),
            [],
            _graph(),
            "credential_gap",
        ),
        (_requirement(None, concept_type="unknown"), [], _graph(), "unknown"),
        (_requirement("missing"), [], _graph(), "absent"),
    ],
)
def test_match_engine_emits_every_precise_status(
    requirement, assertions, graph, expected
):
    from resume_agent.matching.engine import match_requirement

    result = match_requirement(requirement, assertions, graph)

    assert result.status == expected
    assert result.requirement_id == requirement.id
    assert result.matching_policy_revision == "uccm-match-v1"


def test_bounded_traversal_rejects_inactive_low_confidence_scope_and_long_paths():
    from resume_agent.matching.traversal import TraversalPolicy, find_paths

    graph = _graph(
        _edge("a", "same_as", "b"),
        _edge("b", "same_as", "target"),
        _edge("a", "transferable_to", "inactive", status="inactive"),
        _edge("a", "transferable_to", "weak", confidence=0.2),
        _edge("a", "transferable_to", "tenant", scope="tenant"),
        _edge("target", "same_as", "a"),
    )

    paths = find_paths(
        graph,
        start_id="a",
        target_id="target",
        policy=TraversalPolicy(max_depth=2, visible_scopes=frozenset({"global"})),
    )

    assert len(paths) == 1
    assert [step.edge_id for step in paths[0].steps] == [
        "edge:a:same_as:b",
        "edge:b:same_as:target",
    ]
    assert find_paths(
        graph,
        start_id="a",
        target_id="target",
        policy=TraversalPolicy(max_depth=1),
    ) == []


def test_shadow_result_preserves_actual_legacy_coverage_and_candidate_name():
    from resume_agent.matching.engine import shadow_match_requirement

    candidate = _assertion("candidate")
    result = shadow_match_requirement(
        _requirement("target"),
        [candidate],
        _graph(_edge("candidate", "transferable_to", "target")),
        legacy_coverage="adjacent",
    )

    assert result.legacy_coverage == "adjacent"
    assert result.v2.status == "transferable"
    assert result.v2.candidate_label == "Candidate candidate"
    assert result.v2.requirement_label == "Target Capability"
    assert result.v2.candidate_label != result.v2.requirement_label


def test_same_domain_or_lexical_similarity_alone_never_counts_as_coverage():
    from resume_agent.matching.engine import match_requirement

    requirement = _requirement("target")
    candidate = _assertion("target-like-name")

    result = match_requirement(requirement, [candidate], _graph())

    assert result.status == "absent"
    assert result.features.lexical_similarity == 0.0
    assert result.features.learned_domain_match is False


def test_strict_credential_uses_verified_requirement_lane_facts_only():
    from resume_agent.matching.engine import match_requirement
    from resume_agent.matching.models import VerifiedRequirementFact

    requirement = _requirement(
        "credential",
        concept_type="credential",
        strictness="credential",
    )
    assertion_only = match_requirement(
        requirement,
        [_assertion("credential", concept_type="credential")],
        _graph(),
    )
    assert assertion_only.status == "credential_gap"

    verified = VerifiedRequirementFact(
        id="requirement-fact:credential:1",
        fact_type="credential",
        normalized_value="target capability",
        display="Target Capability",
        evidence_fact_id="certification:1",
        verification_status="verified",
    )
    matched = match_requirement(
        requirement,
        [],
        _graph(),
        verified_requirement_facts=[verified],
    )

    assert matched.status == "verified_exact"
    assert matched.verified_requirement_fact_id == verified.id
    assert matched.evidence_fact_ids == ["certification:1"]


def test_strict_product_and_standard_gates_cannot_be_bypassed_by_graph_paths():
    from resume_agent.matching.engine import match_requirement

    product = match_requirement(
        _requirement("target", concept_type="tool_technology", strictness="exact_product"),
        [_assertion("candidate", concept_type="tool_technology")],
        _graph(_edge("candidate", "same_as", "target")),
    )
    standard = match_requirement(
        _requirement("target", concept_type="standard", strictness="method_or_standard"),
        [_assertion("candidate", concept_type="standard")],
        _graph(_edge("candidate", "same_as", "target")),
    )

    assert product.status == "tool_gap"
    assert product.strict_requirement_credit is False
    assert standard.status == "absent"
    assert standard.strict_requirement_credit is False


def test_work_authorization_and_clearance_use_requirement_facts_not_graph_paths():
    from resume_agent.matching.engine import match_requirement
    from resume_agent.matching.models import VerifiedRequirementFact

    authorization = _requirement(
        "requirement:work-authorization",
        concept_type="work_context",
        strictness="contextual",
        requirement_kind="availability_or_location",
        source_text="Work authorization",
        parsed_concept_label="work authorization",
    )
    explicit_fact = VerifiedRequirementFact(
        id="requirement-fact:authorization:1",
        fact_type="work_authorization",
        normalized_value="authorized to work in the united states",
        display="Authorized to work in the United States",
        evidence_fact_id="contact:work_authorization",
        verification_status="asserted",
    )
    matched = match_requirement(
        authorization,
        [_assertion("requirement:work-authorization", concept_type="work_context")],
        _graph(),
        verified_requirement_facts=[explicit_fact],
    )
    assert matched.status == "verified_exact"
    assert matched.verified_requirement_fact_id == explicit_fact.id
    assert matched.strict_requirement_credit is True

    clearance = _requirement(
        "requirement:security-clearance",
        concept_type="work_context",
        strictness="contextual",
        requirement_kind="availability_or_location",
        source_text="Security clearance",
        parsed_concept_label="security clearance",
    )
    blocked = match_requirement(
        clearance,
        [_assertion("candidate")],
        _graph(_edge("candidate", "same_as", "requirement:security-clearance")),
    )
    assert blocked.status == "context_gap"
    assert blocked.strict_requirement_credit is False


def test_broader_candidate_never_receives_strict_credit_without_subskill_evidence():
    from resume_agent.matching.engine import match_requirement

    result = match_requirement(
        _requirement("target"),
        [_assertion("candidate")],
        _graph(_edge("candidate", "broader_than", "target")),
    )

    assert result.status == "covered_broader"
    assert result.strict_requirement_credit is False
