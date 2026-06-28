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
            build_skill_canonicalizer,
            build_skill_themer,
        )

        with open_session(engine) as session:
            return refresh_clusters(
                session,
                dedup=build_skill_canonicalizer(),
                themer=build_skill_themer(),
                path=_CLUSTER_PATH,
                reporter=reporter,
            )

    run_id = mgr.submit("refreshClusters", work)
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(run_id, record)
