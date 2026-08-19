"""Compatibility bridge that records actual legacy and Match v2 together."""

from __future__ import annotations

from collections import defaultdict, deque

from resume_agent.matching.engine import shadow_match_requirement
from resume_agent.matching.models import LegacyCoverage, ShadowMatchResult
from resume_agent.models.job import JobCriteria
from resume_agent.profile.matrix import SkillMatrix, build_skill_match_context
from resume_agent.taxonomy.clusters import ClusterMap
from resume_agent.taxonomy.graph_models import CareerCapabilityGraph
from resume_agent.tracking.match_gap import normalize_skill


class StaleUccmArtifactError(ValueError):
    pass


def build_shadow_matches(
    criteria: JobCriteria,
    matrix: SkillMatrix,
    cluster_map: ClusterMap,
    graph: CareerCapabilityGraph,
    *,
    expected_taxonomy_revision: str,
) -> list[ShadowMatchResult]:
    if matrix.taxonomy_revision != expected_taxonomy_revision:
        raise StaleUccmArtifactError(
            "profile matrix taxonomy revision does not match the effective snapshot"
        )
    mismatched_requirements = [
        requirement.id
        for requirement in criteria.typed_requirements
        if requirement.taxonomy_revision != expected_taxonomy_revision
    ]
    if mismatched_requirements:
        raise StaleUccmArtifactError(
            "typed requirement taxonomy revision does not match the effective snapshot"
        )

    legacy = build_skill_match_context(criteria, matrix, cluster_map)
    legacy_by_key: dict[tuple[str, str], deque[LegacyCoverage]] = defaultdict(deque)
    for match in legacy.matches:
        legacy_by_key[(match.source, normalize_skill(match.requirement))].append(
            match.coverage
        )
    source_map = {"must": "must", "nice": "nice", "tech": "tech"}
    results: list[ShadowMatchResult] = []
    for requirement in criteria.typed_requirements:
        source = source_map.get(requirement.legacy_source)
        queue = (
            legacy_by_key.get((source, normalize_skill(requirement.source_text)))
            if source is not None
            else None
        )
        legacy_coverage: LegacyCoverage = (
            queue.popleft() if queue else "not_evaluated"
        )
        results.append(
            shadow_match_requirement(
                requirement,
                matrix.assertions,
                graph,
                legacy_coverage=legacy_coverage,
                verified_requirement_facts=matrix.verified_requirement_facts,
            )
        )
    return results
