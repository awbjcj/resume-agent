"""Read-only match-gap demand graph and cluster refresh endpoint."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from sqlmodel import Session

from resume_agent.api.deps import get_run_manager, get_session
from resume_agent.api.runs.manager import RunManager
from resume_agent.api.runs.sse import record_to_run
from resume_agent.api.schemas.match_gap import MatchGapOut
from resume_agent.api.schemas.runs import RunOut
from resume_agent.db import get_session as open_session
from resume_agent.models.profile import Contact, ProfileFacts
from resume_agent.profile.matrix import (
    build_matrix,
    load_overrides,
    override_tokens,
    save_matrix,
)
from resume_agent.profile.store import load_facts
from resume_agent.services.suggestions import suggestion_statuses
from resume_agent.taxonomy.clusters import load_cluster_map
from resume_agent.tracking.match_gap import build_demand_graph, profile_skill_tokens

router = APIRouter()

_FACTS_PATH = "data/profile/facts.json"
_CLUSTER_PATH = "data/profile/cluster_map.json"


def _facts_or_empty() -> ProfileFacts:
    if Path(_FACTS_PATH).exists():
        return load_facts(_FACTS_PATH)
    return ProfileFacts(contact=Contact(name=""))


@router.get("/match-gap", response_model=MatchGapOut)
def get_match_gap(session: Session = Depends(get_session)):
    facts = _facts_or_empty()
    graph = build_demand_graph(
        session,
        facts,
        cluster_map=load_cluster_map(_CLUSTER_PATH),
    )
    return MatchGapOut.model_validate(
        {
            **graph.__dict__,
            "suggestion_statuses": suggestion_statuses(
                session, graph, profile_skill_tokens(facts)
            ),
        }
    )


@router.post("/match-gap/refresh-clusters", response_model=RunOut, status_code=202)
def refresh_match_gap_clusters(
    request: Request,
    mgr: RunManager = Depends(get_run_manager),
):
    engine = request.app.state.engine

    def work(reporter):
        from resume_agent.services.match_gap import refresh_clusters
        from resume_agent.tracking.canonicalize import (
            build_incremental_canonicalizer_agent,
            build_incremental_themer_agent,
        )

        facts_path = Path(_FACTS_PATH)
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
                path=_CLUSTER_PATH,
                reporter=reporter,
                extra_tokens=extra_tokens,
            )
        if facts is None:
            result["matrixRegenerated"] = False
            return result

        matrix = build_matrix(
            facts,
            load_cluster_map(_CLUSTER_PATH),
            overrides,
        )
        save_matrix(matrix, facts_path.with_name("matrix.json"))
        result["matrixRegenerated"] = True
        return result

    run_id = mgr.submit(
        "refreshClusters", work, singleton_key="refreshClusters"
    )
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(record)
