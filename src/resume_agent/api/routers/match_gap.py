"""Read-only match-gap demand graph and cluster refresh endpoint."""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from resume_agent.api.deps import get_engine, get_run_manager, get_session
from resume_agent.api.runs.launch import launch
from resume_agent.api.runs.manager import RunManager
from resume_agent.api.schemas.match_gap import MatchGapOut, RefreshClustersIn
from resume_agent.api.schemas.runs import RunOut
from resume_agent.db import get_session as open_session
from resume_agent.models.profile import Contact, ProfileFacts
from resume_agent.profile.matrix import (
    build_matrix,
    decorate_matrix_groups,
    effective_cluster_map,
    load_overrides,
    override_tokens,
    save_matrix,
)
from resume_agent.profile.store import load_facts
from resume_agent.services.suggestions import suggestion_statuses
from resume_agent.taxonomy.clusters import load_cluster_map
from resume_agent.taxonomy.corrections import (
    apply_taxonomy_corrections,
    corrections_file_path,
    load_taxonomy_corrections,
)
from resume_agent.taxonomy.state import load_taxonomy_state
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
    corrections = load_taxonomy_corrections(
        resolve_tenant_path(corrections_file_path())
    )
    cluster_map = apply_taxonomy_corrections(
        effective_cluster_map(
            load_cluster_map(resolve_tenant_path(_CLUSTER_PATH)),
            load_overrides(profile_dir / "overrides.yaml"),
        ),
        corrections,
    )
    taxonomy_state = load_taxonomy_state(resolve_tenant_path(_CLUSTER_PATH))
    graph = build_demand_graph(
        session,
        facts,
        cluster_map=cluster_map,
        corrections=corrections,
        grouping_statuses=taxonomy_state.grouping_status,
    )
    graph.taxonomy_generation = taxonomy_state.generation_id
    graph.taxonomy_algorithm_version = taxonomy_state.algorithm_version
    graph.taxonomy_maintenance_due = taxonomy_state.maintenance_due
    graph.taxonomy_undo_available = taxonomy_state.can_undo
    return MatchGapOut.model_validate(
        {
            **graph.__dict__,
            "suggestion_statuses": suggestion_statuses(
                session, graph, profile_skill_tokens(facts)
            ),
        }
    )


@router.get("/match-gap", response_model=MatchGapOut)
def get_match_gap(session: Session = Depends(get_session)):
    return build_match_gap_payload(session)


def _regenerate_bound_matrix(facts: ProfileFacts | None, facts_path: Path) -> bool:
    if facts is None:
        return False
    profile_dir = facts_path.parent
    overrides = load_overrides(profile_dir / "overrides.yaml")
    matrix = build_matrix(
        facts,
        load_cluster_map(resolve_tenant_path(_CLUSTER_PATH)),
        overrides,
    )
    decorate_matrix_groups(matrix, profile_dir, overrides)
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
        from resume_agent.tracking.canonicalize import (
            build_incremental_canonicalizer_agent,
            build_incremental_themer_agent,
        )

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
                canonicalizer=build_incremental_canonicalizer_agent(),
                themer=build_incremental_themer_agent(),
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
