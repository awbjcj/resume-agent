"""Coherent UCCM projection for the match-gap application boundary."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from sqlmodel import Session

from resume_agent.discovery.requirements import adapt_legacy_requirements
from resume_agent.matching.models import MATCHING_POLICY_REVISION, ShadowMatchResult
from resume_agent.matching.observability import build_uccm_observation
from resume_agent.matching.shadow import StaleUccmArtifactError, build_shadow_matches
from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import ProfileFacts
from resume_agent.models.requirements import JobRequirement
from resume_agent.profile.assertions import ASSERTION_POLICY_REVISION
from resume_agent.profile.matrix import (
    SkillMatrix,
    build_matrix,
    decorate_matrix_groups,
    load_matrix,
    save_matrix,
)
from resume_agent.profile.projections import UccmProfileProjection
from resume_agent.taxonomy.snapshot import EffectiveTaxonomy
from resume_agent.tracking.tables import Job

logger = logging.getLogger(__name__)


@dataclass
class UccmMatchGapProjection:
    state: str = "disabled"
    error_code: str | None = None
    matching_policy_revision: str = ""
    profile_facts_revision: str = ""
    assertion_policy_revision: str = ""
    typed_requirements: list[JobRequirement] = field(default_factory=list)
    match_results: list[ShadowMatchResult] = field(default_factory=list)
    profile_projection: UccmProfileProjection | None = None


def _record_observation(
    projection: UccmMatchGapProjection,
    taxonomy: EffectiveTaxonomy,
    matrix: SkillMatrix | None = None,
) -> None:
    assertions = matrix.assertions if matrix is not None else []
    observed_decisions = {
        item.term_decision_id for item in assertions
    } | {
        item.term_decision_id for item in projection.typed_requirements
    }
    observation = build_uccm_observation(
        assertion_statuses=(item.assertion_status for item in assertions),
        assertion_types=(item.concept_type for item in assertions),
        requirement_types=(
            item.concept_type for item in projection.typed_requirements
        ),
        match_statuses=(item.v2.status for item in projection.match_results),
        correction_count=sum(
            event.subject_decision_id in observed_decisions
            for event in taxonomy.term_type_corrections
        ),
        fallback=taxonomy.manifest.capability_status == "fallback",
        stale=projection.state == "stale",
    )
    logger.info(
        "UCCM runtime observation",
        extra={"uccm_observation": observation.log_fields()},
    )


def _coherent_matrix(
    facts: ProfileFacts,
    taxonomy: EffectiveTaxonomy,
    profile_dir: Path,
) -> SkillMatrix:
    matrix_path = profile_dir / "matrix.json"
    matrix = load_matrix(matrix_path, facts=facts, taxonomy=taxonomy)
    if matrix is None:
        matrix = build_matrix(facts, taxonomy)
        decorate_matrix_groups(matrix, profile_dir, taxonomy)
        save_matrix(matrix, matrix_path)
    return matrix


def build_uccm_match_gap_projection(
    session: Session,
    *,
    facts: ProfileFacts,
    taxonomy: EffectiveTaxonomy,
    profile_dir: Path,
    job_ids: list[int],
) -> UccmMatchGapProjection:
    if taxonomy.manifest.capability_status == "disabled":
        result = UccmMatchGapProjection()
        _record_observation(result, taxonomy)
        return result
    snapshot = taxonomy.capability_snapshot
    if snapshot is None:
        result = UccmMatchGapProjection(
            state="unavailable",
            error_code=taxonomy.manifest.capability_error_code or "graph_unavailable",
        )
        _record_observation(result, taxonomy)
        return result
    matrix = _coherent_matrix(facts, taxonomy, profile_dir)
    projection = UccmMatchGapProjection(
        state="ready",
        matching_policy_revision=MATCHING_POLICY_REVISION,
        profile_facts_revision=matrix.facts_sha256,
        assertion_policy_revision=matrix.assertion_policy_revision
        or ASSERTION_POLICY_REVISION,
        profile_projection=matrix.uccm_profile,
    )
    for job_id in job_ids:
        job = session.get(Job, job_id)
        if job is None:
            continue
        criteria = JobCriteria.model_validate(job.criteria_json or {})
        if not criteria.typed_requirements:
            criteria = criteria.model_copy(
                update={
                    "typed_requirements": adapt_legacy_requirements(
                        criteria,
                        job_id=job_id,
                        taxonomy_revision=taxonomy.semantic_revision,
                        aliases=taxonomy.cluster_map.aliases,
                        term_corrections=list(taxonomy.term_type_corrections),
                    )
                }
            )
        try:
            results = build_shadow_matches(
                criteria,
                matrix,
                taxonomy.cluster_map,
                snapshot.graph,
                expected_taxonomy_revision=taxonomy.semantic_revision,
            )
        except StaleUccmArtifactError:
            result = UccmMatchGapProjection(
                state="stale",
                error_code="artifact_revision_mismatch",
                matching_policy_revision=MATCHING_POLICY_REVISION,
                profile_facts_revision=matrix.facts_sha256,
                assertion_policy_revision=matrix.assertion_policy_revision,
                profile_projection=matrix.uccm_profile,
            )
            _record_observation(result, taxonomy, matrix)
            return result
        projection.typed_requirements.extend(criteria.typed_requirements)
        projection.match_results.extend(results)
    _record_observation(projection, taxonomy, matrix)
    return projection
