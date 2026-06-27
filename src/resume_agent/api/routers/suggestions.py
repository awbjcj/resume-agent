"""Gap-closing advisor cached reads and generation runs."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, select

from resume_agent.api.deps import get_run_manager, get_session
from resume_agent.api.errors import ApiException
from resume_agent.api.runs.manager import RunManager
from resume_agent.api.runs.sse import record_to_run
from resume_agent.api.schemas.runs import RunOut
from resume_agent.api.schemas.suggestions import SuggestionEnvelope, SuggestionOut
from resume_agent.db import get_session as open_session
from resume_agent.github.repos import verify_repo
from resume_agent.models.profile import Contact, ProfileFacts
from resume_agent.profile.store import load_facts
from resume_agent.services.suggestions import (
    SuggestionContext,
    SuggestionTargetNotFound,
    generate_suggestion,
    resolve_suggestion_context,
    suggestion_fingerprint,
)
from resume_agent.suggestions.agents import build_formatter_agent, build_search_agent
from resume_agent.taxonomy.clusters import load_cluster_map
from resume_agent.tracking.match_gap import build_demand_graph, profile_skill_tokens
from resume_agent.tracking.tables import SkillSuggestion

router = APIRouter()

SuggestionKind = Literal["skill", "theme"]
_FACTS_PATH = "data/profile/facts.json"
_CLUSTER_PATH = "data/profile/cluster_map.json"


class GenerateParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: SuggestionKind
    key: str = Field(min_length=1, max_length=200)


def _facts_or_empty() -> ProfileFacts:
    if Path(_FACTS_PATH).exists():
        return load_facts(_FACTS_PATH)
    return ProfileFacts(contact=Contact(name=""))


def _resolve_context(
    session: Session,
    facts: ProfileFacts,
    *,
    kind: SuggestionKind,
    key: str,
) -> SuggestionContext:
    graph = build_demand_graph(
        session,
        facts,
        cluster_map=load_cluster_map(_CLUSTER_PATH),
    )
    try:
        return resolve_suggestion_context(graph, kind=kind, key=key)
    except SuggestionTargetNotFound as exc:
        raise ApiException(404, "NOT_FOUND", str(exc)) from exc


@router.get("/suggestions", response_model=SuggestionEnvelope)
def get_suggestion(
    kind: SuggestionKind,
    key: Annotated[str, Query(min_length=1, max_length=200)],
    session: Session = Depends(get_session),
):
    facts = _facts_or_empty()
    context = _resolve_context(session, facts, kind=kind, key=key)
    row = session.exec(
        select(SkillSuggestion).where(
            SkillSuggestion.kind == kind,
            SkillSuggestion.key == key,
        )
    ).first()
    if row is None:
        return SuggestionEnvelope(suggestion=None, stale=False)

    current_fingerprint = suggestion_fingerprint(context, profile_skill_tokens(facts))
    suggestion = SuggestionOut(
        kind=row.kind,
        key=row.key,
        generated_at=row.generated_at,
        **row.payload_json,
    )
    return SuggestionEnvelope(
        suggestion=suggestion,
        stale=row.fingerprint != current_fingerprint,
    )


@router.post("/suggestions/generate", response_model=RunOut, status_code=202)
def launch_generate(
    params: GenerateParams,
    request: Request,
    session: Session = Depends(get_session),
    mgr: RunManager = Depends(get_run_manager),
):
    _resolve_context(session, _facts_or_empty(), kind=params.kind, key=params.key)
    engine = request.app.state.engine
    github_token = request.app.state.settings.github_token

    def work(reporter):
        reporter.begin(1, f"Researching {params.key}")
        with open_session(engine) as worker_session:
            facts = _facts_or_empty()
            context = _resolve_context(
                worker_session,
                facts,
                kind=params.kind,
                key=params.key,
            )
            row = generate_suggestion(
                worker_session,
                context=context,
                search_agent=build_search_agent(),
                formatter=build_formatter_agent(),
                verify=lambda owner, name: verify_repo(
                    owner,
                    name,
                    token=github_token,
                ),
                facts=facts,
                reporter=reporter,
            )
        reporter.step(1)
        return {"kind": row.kind, "key": row.key}

    run_id = mgr.submit("suggestion", work)
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(run_id, record)
