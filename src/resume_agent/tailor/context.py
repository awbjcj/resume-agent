"""Pinned UCCM tailoring context and its compatibility projection."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from resume_agent.matching.models import (
    MATCHING_POLICY_REVISION,
    MatchStatus,
    ShadowMatchResult,
)
from resume_agent.models.base import ExtensibleModel
from resume_agent.models.requirements import (
    JOB_EXTRACTION_POLICY_REVISION,
    JobRequirement,
)
from resume_agent.profile.assertions import CapabilityAssertion
from resume_agent.profile.matrix import MatrixRow, SkillMatch, SkillMatchContext, SkillMatrix

_DIRECT_STATUSES: frozenset[MatchStatus] = frozenset(
    {
        "verified_exact",
        "verified_equivalent",
        "covered_broader",
        "covered_narrower",
    }
)
_ADJACENT_STATUSES: frozenset[MatchStatus] = frozenset({"transferable", "partial"})


class UccmTailoringContext(ExtensibleModel):
    """Complete immutable inputs used to shape one tailoring attempt."""

    taxonomy_revision: str
    facts_revision: str
    assertion_policy_revision: str
    extraction_policy_revision: str
    matching_policy_revision: str
    requirement_ids: list[str] = Field(default_factory=list)
    result_ids: list[str] = Field(default_factory=list)
    assertion_ids: list[str] = Field(default_factory=list)
    requirements: list[JobRequirement] = Field(default_factory=list)
    shadow_results: list[ShadowMatchResult] = Field(default_factory=list)
    assertions: list[CapabilityAssertion] = Field(default_factory=list)


def _only_revision(values: set[str], *, label: str, fallback: str) -> str:
    values.discard("")
    if len(values) > 1:
        raise ValueError(f"mixed {label} revisions")
    return next(iter(values), fallback)


def build_uccm_tailoring_context(
    *,
    matrix: SkillMatrix,
    requirements: list[JobRequirement],
    shadow_results: list[ShadowMatchResult],
) -> UccmTailoringContext:
    """Validate artifact coherence and freeze the exact inputs for tailoring."""
    requirement_ids = [requirement.id for requirement in requirements]
    result_requirement_ids = [result.v2.requirement_id for result in shadow_results]
    if requirement_ids != result_requirement_ids:
        raise ValueError("tailoring requirements and match results are not aligned")
    taxonomy_revisions = {
        matrix.taxonomy_revision,
        *(requirement.taxonomy_revision for requirement in requirements),
        *(result.v2.taxonomy_revision for result in shadow_results),
    }
    taxonomy_revision = _only_revision(
        taxonomy_revisions,
        label="taxonomy",
        fallback=matrix.taxonomy_revision,
    )
    if taxonomy_revision != matrix.taxonomy_revision:
        raise ValueError("tailoring taxonomy revision does not match profile matrix")
    facts_revision = _only_revision(
        {
            matrix.facts_sha256,
            *(result.v2.facts_revision or "" for result in shadow_results),
        },
        label="facts",
        fallback=matrix.facts_sha256,
    )
    assertion_policy_revision = _only_revision(
        {
            matrix.assertion_policy_revision,
            *(result.v2.assertion_policy_revision or "" for result in shadow_results),
        },
        label="assertion policy",
        fallback=matrix.assertion_policy_revision,
    )
    extraction_policy_revision = _only_revision(
        {
            *(requirement.extraction_policy_revision for requirement in requirements),
            *(result.v2.extraction_policy_revision for result in shadow_results),
        },
        label="extraction policy",
        fallback=JOB_EXTRACTION_POLICY_REVISION,
    )
    matching_policy_revision = _only_revision(
        {result.v2.matching_policy_revision for result in shadow_results},
        label="matching policy",
        fallback=MATCHING_POLICY_REVISION,
    )
    assertion_by_id = {assertion.id: assertion for assertion in matrix.assertions}
    assertion_ids = list(
        dict.fromkeys(
            result.v2.assertion_id
            for result in shadow_results
            if result.v2.assertion_id is not None
        )
    )
    missing = [assertion_id for assertion_id in assertion_ids if assertion_id not in assertion_by_id]
    if missing:
        raise ValueError("match result references an assertion outside the profile matrix")
    return UccmTailoringContext(
        taxonomy_revision=taxonomy_revision,
        facts_revision=facts_revision,
        assertion_policy_revision=assertion_policy_revision,
        extraction_policy_revision=extraction_policy_revision,
        matching_policy_revision=matching_policy_revision,
        requirement_ids=requirement_ids,
        result_ids=[result.v2.id for result in shadow_results],
        assertion_ids=assertion_ids,
        requirements=requirements,
        shadow_results=shadow_results,
        assertions=[assertion_by_id[assertion_id] for assertion_id in assertion_ids],
    )


def _matrix_row(assertion: CapabilityAssertion | None) -> MatrixRow | None:
    if assertion is None:
        return None
    projection = assertion.legacy_projection
    return MatrixRow(
        key=projection.key,
        display=projection.display,
        aliases=projection.aliases,
        category=projection.category,
        inferred=projection.inferred,
        evidence_fact_ids=assertion.evidence_fact_ids,
        strength=projection.strength,
        last_used=assertion.last_used,
    )


def _legacy_coverage(status: MatchStatus, has_candidate: bool) -> Literal["covered", "adjacent", "gap"]:
    if status in _DIRECT_STATUSES:
        return "covered"
    if status in _ADJACENT_STATUSES and has_candidate:
        return "adjacent"
    return "gap"


def project_legacy_skill_context(context: UccmTailoringContext) -> SkillMatchContext:
    """Project v2 results once; this adapter never invokes either matcher."""
    assertions = {assertion.id: assertion for assertion in context.assertions}
    requirements = {requirement.id: requirement for requirement in context.requirements}
    matches: list[SkillMatch] = []
    for shadow in context.shadow_results:
        requirement = requirements[shadow.v2.requirement_id]
        if requirement.legacy_source == "derived":
            continue
        assertion = (
            assertions.get(shadow.v2.assertion_id)
            if shadow.v2.assertion_id is not None
            else None
        )
        row = _matrix_row(assertion)
        coverage = _legacy_coverage(shadow.v2.status, row is not None)
        matches.append(
            SkillMatch(
                requirement=requirement.source_text,
                source=requirement.legacy_source,
                coverage=coverage,
                row=row if coverage != "gap" else None,
            )
        )
    return SkillMatchContext(matches=matches)
