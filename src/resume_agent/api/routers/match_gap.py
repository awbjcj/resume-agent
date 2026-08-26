"""Read-only match-gap demand graph and cluster refresh endpoint."""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from resume_agent.api.deps import get_engine, get_run_manager, get_session
from resume_agent.api.runs.launch import launch
from resume_agent.api.runs.manager import RunManager
from resume_agent.api.schemas.match_gap import (
    MatchGapOut,
    OverrideConflictOut,
    RefreshClustersIn,
    RestoreSkillsIn,
    RestoreSkillsOut,
    TaxonomyManifestOut,
)
from resume_agent.api.schemas.runs import RunOut
from resume_agent.db import get_session as open_session
from resume_agent.models.profile import Contact, ProfileFacts
from resume_agent.profile.effective import build_effective_taxonomy
from resume_agent.profile.matrix import (
    build_matrix,
    decorate_matrix_groups,
    load_overrides,
    override_tokens,
    save_matrix,
)
from resume_agent.profile.store import load_facts
from resume_agent.services.suggestions import suggestion_statuses
from resume_agent.taxonomy.corrections import corrections_file_path
from resume_agent.tracking.match_gap import build_demand_graph, profile_skill_tokens
from resume_agent.tenancy.paths import FACTS_PATH as _FACTS_PATH, resolve_tenant_path

router = APIRouter()

_CLUSTER_PATH = "data/profile/cluster_map.json"


def _facts_or_empty() -> ProfileFacts:
    if resolve_tenant_path(_FACTS_PATH).exists():
        return load_facts(_FACTS_PATH)
    return ProfileFacts(contact=Contact(name=""))


def build_match_gap_payload(session: Session) -> MatchGapOut:
    facts = _facts_or_empty()
    facts_path = resolve_tenant_path(_FACTS_PATH)
    profile_dir = facts_path.parent
    taxonomy = build_effective_taxonomy(profile_dir)
    graph = build_demand_graph(
        session,
        facts,
        cluster_map=taxonomy.cluster_map,
        corrections=taxonomy.corrections,
        grouping_statuses=taxonomy.state.grouping_status,
    )
    graph.taxonomy_generation = taxonomy.state.generation_id
    graph.taxonomy_algorithm_version = taxonomy.state.algorithm_version
    graph.taxonomy_maintenance_due = taxonomy.state.maintenance_due
    graph.taxonomy_undo_available = taxonomy.state.can_undo
    return MatchGapOut.model_validate(
        {
            **graph.__dict__,
            "suggestion_statuses": suggestion_statuses(
                session, graph, profile_skill_tokens(facts)
            ),
            "retired_skills": [
                {
                    "key": key,
                    "reason": retired.reason,
                    "retired_at": retired.retired_at,
                }
                for key, retired in sorted(taxonomy.state.retired_skills.items())
            ],
            "taxonomy_revision": taxonomy.semantic_revision,
            "taxonomy_manifest": TaxonomyManifestOut(
                **asdict(taxonomy.manifest)
            ),
            "override_conflicts": [
                OverrideConflictOut(**asdict(conflict))
                for conflict in taxonomy.conflicts
            ],
        }
    )


@router.get("/match-gap", response_model=MatchGapOut)
def get_match_gap(session: Session = Depends(get_session)):
    return build_match_gap_payload(session)


def _regenerate_bound_matrix(facts: ProfileFacts | None, facts_path: Path) -> bool:
    if facts is None:
        return False
    profile_dir = facts_path.parent
    taxonomy = build_effective_taxonomy(profile_dir)
    matrix = build_matrix(facts, taxonomy)
    decorate_matrix_groups(matrix, profile_dir, taxonomy)
    save_matrix(matrix, facts_path.with_name("matrix.json"))
    return True


@router.post("/match-gap/refresh-clusters", response_model=RunOut, status_code=202)
def refresh_match_gap_clusters(
    request: Request,
    body: RefreshClustersIn | None = None,
    mgr: RunManager = Depends(get_run_manager),
):
    engine = get_engine(request)
    scoped_keys = set(body.skill_keys) if body is not None else None
    fingerprint = (
        "all"
        if scoped_keys is None
        else hashlib.sha256("\x1f".join(sorted(scoped_keys)).encode()).hexdigest()[:20]
    )

    def work(reporter):
        from resume_agent.services.match_gap import refresh_clusters

        facts_path = resolve_tenant_path(_FACTS_PATH)
        overrides = load_overrides(facts_path.with_name("overrides.yaml"))
        extra_tokens = override_tokens(overrides)
        try:
            facts = load_facts(facts_path)
        except (OSError, ValueError):
            facts = None
        if facts is not None:
            extra_tokens |= profile_skill_tokens(facts)

        with open_session(engine) as session:
            result = refresh_clusters(
                session,
                path=resolve_tenant_path(_CLUSTER_PATH),
                reporter=reporter,
                extra_tokens=extra_tokens,
                corrections_path=resolve_tenant_path(corrections_file_path()),
                skill_keys=scoped_keys,
            )
        result["matrixRegenerated"] = _regenerate_bound_matrix(facts, facts_path)
        return result

    return launch(
        mgr,
        "refreshClusters",
        work,
        singleton_key=f"refreshClusters:{fingerprint}",
        meta={"skillKeys": sorted(scoped_keys) if scoped_keys is not None else None},
    )


@router.post("/match-gap/restore-skills", response_model=RestoreSkillsOut)
def restore_match_gap_skills(body: RestoreSkillsIn):
    """Un-retire skills so the next regroup treats them as real again.

    Deliberately synchronous: this only edits the taxonomy state file, so a run
    record and an SSE stream would be pure ceremony.
    """

    from resume_agent.services.match_gap import restore_skills

    result = restore_skills(
        path=resolve_tenant_path(_CLUSTER_PATH), skill_keys=set(body.skill_keys)
    )
    return RestoreSkillsOut.model_validate(result)


@router.post("/match-gap/maintain-taxonomy", response_model=RunOut, status_code=202)
def maintain_match_gap_taxonomy(
    request: Request,
    mgr: RunManager = Depends(get_run_manager),
):
    engine = get_engine(request)

    def work(_reporter):
        from resume_agent.services.match_gap import maintain_taxonomy
        from resume_agent.tracking.canonicalize import build_taxonomy_maintenance_agent

        facts_path = resolve_tenant_path(_FACTS_PATH)
        try:
            facts = load_facts(facts_path)
        except (OSError, ValueError):
            facts = None
        with open_session(engine) as session:
            result = maintain_taxonomy(
                session,
                judge=build_taxonomy_maintenance_agent(),
                path=resolve_tenant_path(_CLUSTER_PATH),
                corrections_path=resolve_tenant_path(corrections_file_path()),
            )
        result["matrixRegenerated"] = _regenerate_bound_matrix(facts, facts_path)
        return result

    return launch(
        mgr,
        "maintainTaxonomy",
        work,
        singleton_key="taxonomyMaintenance",
    )


@router.post(
    "/match-gap/undo-taxonomy-maintenance", response_model=RunOut, status_code=202
)
def undo_match_gap_taxonomy_maintenance(
    request: Request,
    mgr: RunManager = Depends(get_run_manager),
):
    engine = get_engine(request)

    def work(_reporter):
        from resume_agent.services.match_gap import undo_taxonomy_maintenance

        facts_path = resolve_tenant_path(_FACTS_PATH)
        try:
            facts = load_facts(facts_path)
        except (OSError, ValueError):
            facts = None
        with open_session(engine) as session:
            result = undo_taxonomy_maintenance(
                session,
                path=resolve_tenant_path(_CLUSTER_PATH),
                corrections_path=resolve_tenant_path(corrections_file_path()),
            )
        result["matrixRegenerated"] = _regenerate_bound_matrix(facts, facts_path)
        return result

    return launch(
        mgr,
        "undoTaxonomyMaintenance",
        work,
        singleton_key="taxonomyMaintenance",
    )
