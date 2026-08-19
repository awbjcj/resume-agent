"""Deterministic per-requirement UCCM matching policy."""

from __future__ import annotations

import hashlib
import json
import re

from resume_agent.matching.models import (
    MATCHING_POLICY_REVISION,
    LegacyCoverage,
    MatchFeatureVector,
    MatchStatus,
    MatchV2Result,
    RelationshipPath,
    ShadowMatchResult,
    VerifiedRequirementFact,
)
from resume_agent.matching.traversal import TraversalPolicy, find_paths
from resume_agent.models.requirements import JobRequirement
from resume_agent.profile.assertions import CapabilityAssertion
from resume_agent.taxonomy.graph_models import CareerCapabilityGraph, EdgeType
from resume_agent.tracking.match_gap import normalize_skill

_YEAR = re.compile(r"(?:19|20)\d{2}")
_RELATION_STATUS = {
    "same_as": "verified_equivalent",
    "equivalent_in_context": "verified_equivalent",
    "broader_than": "covered_broader",
    "narrower_than": "covered_narrower",
    "transferable_to": "transferable",
    "prerequisite_for": "partial",
    "requires_capability": "partial",
    "requires_knowledge": "partial",
    "supports_task": "partial",
}
_CONFIDENCE: dict[MatchStatus, float] = {
    "verified_exact": 0.99,
    "verified_equivalent": 0.97,
    "covered_broader": 0.9,
    "covered_narrower": 0.9,
    "transferable": 0.75,
    "partial": 0.6,
    "level_gap": 0.95,
    "context_gap": 0.9,
    "recency_gap": 0.9,
    "evidence_gap": 0.9,
    "tool_gap": 0.98,
    "credential_gap": 0.99,
    "unknown": 0.2,
    "absent": 0.9,
}
_ACTIONS: dict[MatchStatus, str] = {
    "verified_exact": "use_evidence",
    "verified_equivalent": "use_evidence_with_equivalence",
    "covered_broader": "verify_required_specificity",
    "covered_narrower": "use_scoped_evidence",
    "transferable": "describe_candidate_capability_and_bridge",
    "partial": "identify_missing_subskills",
    "level_gap": "develop_proficiency",
    "context_gap": "build_context_evidence",
    "recency_gap": "refresh_recent_evidence",
    "evidence_gap": "collect_direct_evidence",
    "tool_gap": "gain_required_tool_evidence",
    "credential_gap": "verify_or_obtain_credential",
    "unknown": "clarify_requirement",
    "absent": "develop_capability",
}


def _result_id(requirement_id: str, assertion_id: str | None, status: str) -> str:
    payload = json.dumps(
        {
            "requirement_id": requirement_id,
            "assertion_id": assertion_id,
            "status": status,
            "policy": MATCHING_POLICY_REVISION,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "match:" + hashlib.sha256(payload.encode()).hexdigest()


def _path_status(path: RelationshipPath) -> MatchStatus:
    predicates = [step.predicate for step in path.steps]
    if predicates and all(
        predicate in {"same_as", "equivalent_in_context"}
        for predicate in predicates
    ):
        return "verified_equivalent"
    for predicate in (
        "broader_than",
        "narrower_than",
        "transferable_to",
        "prerequisite_for",
        "requires_capability",
        "requires_knowledge",
        "supports_task",
    ):
        if predicate in predicates:
            return _RELATION_STATUS[predicate]  # type: ignore[return-value]
    return "absent"


def _year(value: str | None) -> int | None:
    match = _YEAR.search(value or "")
    return int(match.group()) if match else None


def _deficit_status(
    requirement: JobRequirement,
    assertion: CapabilityAssertion,
) -> MatchStatus | None:
    if requirement.minimum_proficiency is not None and (
        assertion.proficiency_level is None
        or assertion.proficiency_level < requirement.minimum_proficiency
    ):
        return "level_gap"
    if requirement.context:
        candidate_context = (assertion.context or "").casefold()
        if not candidate_context or not all(
            value.casefold() in candidate_context
            for value in requirement.context.values()
        ):
            return "context_gap"
    required_year = _year(requirement.recency_constraint)
    last_year = _year(assertion.last_used)
    if required_year is not None and assertion.last_used != "current" and (
        last_year is None or last_year < required_year
    ):
        return "recency_gap"
    if assertion.claimability not in {
        "literal_evidenced",
        "supported_inference",
        "assessment_validated",
    } or not assertion.evidence_fact_ids:
        return "evidence_gap"
    return None


def _features(
    requirement: JobRequirement,
    assertion: CapabilityAssertion | None,
    path: RelationshipPath | None,
) -> MatchFeatureVector:
    predicates: list[EdgeType] = (
        [step.predicate for step in path.steps] if path is not None else []
    )
    return MatchFeatureVector(
        canonical_identity=(
            assertion is not None
            and requirement.parsed_concept_id == assertion.concept_id
        ),
        approved_equivalence=bool(predicates)
        and all(
            predicate in {"same_as", "equivalent_in_context"}
            for predicate in predicates
        ),
        relationship_predicates=predicates,
        relationship_direction="candidate_to_requirement" if predicates else None,
        proficiency_sufficient=(
            None
            if assertion is None or requirement.minimum_proficiency is None
            else assertion.proficiency_level is not None
            and assertion.proficiency_level >= requirement.minimum_proficiency
        ),
        recency_sufficient=(
            None
            if assertion is None or requirement.recency_constraint is None
            else _deficit_status(requirement, assertion) != "recency_gap"
        ),
        evidence_directness=(
            1.0
            if assertion is not None
            and assertion.claimability in {
                "literal_evidenced",
                "assessment_validated",
            }
            else 0.7
            if assertion is not None
            and assertion.claimability == "supported_inference"
            else 0.0
        ),
        evidence_confidence=(
            assertion.evidence_confidence if assertion is not None else None
        ),
        requirement_importance=requirement.importance,
        strictness=requirement.strictness,
        lexical_similarity=0.0,
        embedding_similarity=0.0,
        learned_domain_match=False,
    )


def match_requirement(
    requirement: JobRequirement,
    assertions: list[CapabilityAssertion],
    graph: CareerCapabilityGraph,
    *,
    traversal_policy: TraversalPolicy | None = None,
    verified_requirement_facts: list[VerifiedRequirementFact] | None = None,
) -> MatchV2Result:
    candidate: CapabilityAssertion | None = None
    verified_fact: VerifiedRequirementFact | None = None
    path: RelationshipPath | None = None
    if requirement.concept_type == "unknown" or requirement.parsed_concept_id is None:
        status: MatchStatus = "unknown"
    elif requirement.strictness == "credential":
        verified_fact = next(
            (
                fact
                for fact in verified_requirement_facts or []
                if fact.fact_type == "credential"
                and fact.verification_status == "verified"
                and fact.normalized_value
                == normalize_skill(requirement.parsed_concept_label)
            ),
            None,
        )
        status = "verified_exact" if verified_fact is not None else "credential_gap"
    else:
        candidate = next(
            (
                assertion
                for assertion in assertions
                if assertion.concept_id == requirement.parsed_concept_id
            ),
            None,
        )
        if candidate is not None:
            status = "verified_exact"
        else:
            related: list[
                tuple[MatchStatus, CapabilityAssertion, RelationshipPath]
            ] = []
            for assertion in assertions:
                paths = find_paths(
                    graph,
                    start_id=assertion.concept_id,
                    target_id=requirement.parsed_concept_id,
                    policy=traversal_policy,
                )
                if paths:
                    related.append((_path_status(paths[0]), assertion, paths[0]))
            precedence = {
                "verified_equivalent": 0,
                "covered_broader": 1,
                "covered_narrower": 2,
                "transferable": 3,
                "partial": 4,
                "absent": 5,
            }
            if related:
                status, candidate, path = min(
                    related,
                    key=lambda item: (
                        precedence[item[0]],
                        len(item[2].steps),
                        item[1].id,
                    ),
                )
            elif requirement.strictness == "exact_product":
                status = "tool_gap"
            else:
                status = "absent"
        if candidate is not None and status in {
            "verified_exact",
            "verified_equivalent",
            "covered_broader",
            "covered_narrower",
        }:
            status = _deficit_status(requirement, candidate) or status

    features = _features(requirement, candidate, path)
    assertion_id = candidate.id if candidate is not None else None
    strict_credit = verified_fact is not None or status in {
        "verified_exact",
        "verified_equivalent",
        "covered_broader",
        "covered_narrower",
    }
    evidence_fact_ids = (
        [verified_fact.evidence_fact_id]
        if verified_fact is not None
        else candidate.evidence_fact_ids
        if candidate is not None
        else []
    )
    return MatchV2Result(
        id=_result_id(requirement.id, assertion_id, status),
        requirement_id=requirement.id,
        status=status,
        confidence=_CONFIDENCE[status],
        requirement_concept_id=requirement.parsed_concept_id,
        requirement_label=requirement.source_text,
        assertion_id=assertion_id,
        verified_requirement_fact_id=(
            verified_fact.id if verified_fact is not None else None
        ),
        candidate_concept_id=candidate.concept_id if candidate is not None else None,
        candidate_label=(
            verified_fact.display
            if verified_fact is not None
            else candidate.legacy_projection.display
            if candidate is not None
            else None
        ),
        relationship_path=path,
        features=features,
        evidence_fact_ids=evidence_fact_ids,
        explanation_code=f"match_status:{status}",
        recommended_action=_ACTIONS[status],
        taxonomy_revision=requirement.taxonomy_revision,
        facts_revision=(
            verified_fact.facts_revision
            if verified_fact is not None
            else candidate.facts_revision
            if candidate is not None
            else None
        ),
        assertion_policy_revision=(
            candidate.assertion_policy_revision if candidate is not None else None
        ),
        extraction_policy_revision=requirement.extraction_policy_revision,
        strict_requirement_credit=strict_credit,
    )


def shadow_match_requirement(
    requirement: JobRequirement,
    assertions: list[CapabilityAssertion],
    graph: CareerCapabilityGraph,
    *,
    legacy_coverage: LegacyCoverage,
    traversal_policy: TraversalPolicy | None = None,
) -> ShadowMatchResult:
    return ShadowMatchResult(
        legacy_coverage=legacy_coverage,
        v2=match_requirement(
            requirement,
            assertions,
            graph,
            traversal_policy=traversal_policy,
        ),
    )
