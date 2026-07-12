"""Gap-closing advisor cached reads and generation runs."""

from __future__ import annotations

from typing import cast
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlmodel import Session

from resume_agent.api.deps import get_engine, get_run_manager, get_session
from resume_agent.api.errors import ApiException
from resume_agent.api.runs.manager import RunManager
from resume_agent.api.runs.sse import record_to_run
from resume_agent.api.schemas.runs import RunOut
from resume_agent.api.schemas.suggestions import (
    SuggestionEnvelope,
    SuggestionOut,
    SuggestionRunAcceptedOut,
    SuggestionRunNotFoundOut,
    SuggestionRunsOut,
    SuggestionRunsRequest,
    SuggestionTarget,
)
from resume_agent.models.profile import ProfileFacts
from resume_agent.services.suggestion_runs import (
    load_suggestion_graph,
    submit_suggestion_run,
)
from resume_agent.services.suggestions import (
    SuggestionContext,
    SuggestionTargetNotFound,
    find_suggestion_row,
    resolve_suggestion_context,
    suggestion_fingerprint,
)
from resume_agent.tracking.match_gap import profile_skill_tokens
from resume_agent.tenancy.context import current_context
from resume_agent.config import get_settings

router = APIRouter()

SuggestionKind = Literal["skill", "theme"]
_FACTS_PATH = "data/profile/facts.json"
_CLUSTER_PATH = "data/profile/cluster_map.json"


def _artifact_paths() -> tuple[str, str]:
    context = current_context()
    if context is None:
        return _FACTS_PATH, _CLUSTER_PATH
    return (
        str(context.paths.profile_dir / "facts.json"),
        str(context.paths.profile_dir / "cluster_map.json"),
    )


def _resolve_context(
    session: Session,
    *,
    kind: SuggestionKind,
    key: str,
) -> tuple[SuggestionContext, ProfileFacts]:
    facts_path, cluster_path = _artifact_paths()
    facts, graph = load_suggestion_graph(
        session,
        facts_path=facts_path,
        cluster_path=cluster_path,
    )
    try:
        return resolve_suggestion_context(graph, kind=kind, key=key), facts
    except SuggestionTargetNotFound as exc:
        raise ApiException(404, "NOT_FOUND", str(exc)) from exc


@router.get("/suggestions", response_model=SuggestionEnvelope)
def get_suggestion(
    kind: SuggestionKind,
    key: Annotated[str, Query(min_length=1, max_length=200)],
    session: Session = Depends(get_session),
):
    context, facts = _resolve_context(session, kind=kind, key=key)
    row = find_suggestion_row(session, context)
    if row is None:
        return SuggestionEnvelope(suggestion=None, stale=False)

    current_fingerprint = suggestion_fingerprint(context, profile_skill_tokens(facts))
    suggestion = SuggestionOut(
        kind=cast(SuggestionKind, row.kind),
        key=context.key,
        generated_at=row.generated_at,
        **row.payload_json,
    )
    return SuggestionEnvelope(
        suggestion=suggestion,
        stale=row.fingerprint != current_fingerprint,
    )


@router.post("/suggestions/generate", response_model=RunOut, status_code=202)
def launch_generate(
    params: SuggestionTarget,
    request: Request,
    session: Session = Depends(get_session),
    mgr: RunManager = Depends(get_run_manager),
):
    context, _facts = _resolve_context(session, kind=params.kind, key=params.key)
    facts_path, cluster_path = _artifact_paths()
    run_id = submit_suggestion_run(
        mgr,
        engine=get_engine(request),
        github_token=get_settings().github_token,
        context=context,
        facts_path=facts_path,
        cluster_path=cluster_path,
    )
    record = mgr.get(run_id)
    assert record is not None
    return record_to_run(record)


@router.post("/suggestion-runs", response_model=SuggestionRunsOut, status_code=202)
def launch_suggestion_runs(
    params: SuggestionRunsRequest,
    request: Request,
    session: Session = Depends(get_session),
    mgr: RunManager = Depends(get_run_manager),
):
    facts_path, cluster_path = _artifact_paths()
    _facts, graph = load_suggestion_graph(
        session,
        facts_path=facts_path,
        cluster_path=cluster_path,
    )
    results: list[SuggestionRunAcceptedOut | SuggestionRunNotFoundOut] = []
    seen_inputs: set[tuple[str, str]] = set()
    seen_targets: set[tuple[str, str]] = set()
    for target in params.targets:
        input_identity = (target.kind, target.key)
        if input_identity in seen_inputs:
            continue
        seen_inputs.add(input_identity)
        try:
            context = resolve_suggestion_context(
                graph,
                kind=target.kind,
                key=target.key,
            )
        except SuggestionTargetNotFound:
            results.append(
                SuggestionRunNotFoundOut(
                    outcome="not_found",
                    kind=target.kind,
                    key=target.key,
                )
            )
            continue

        identity = (context.kind, context.key)
        if identity in seen_targets:
            continue
        seen_targets.add(identity)
        run_id = submit_suggestion_run(
            mgr,
            engine=get_engine(request),
            github_token=get_settings().github_token,
            context=context,
            facts_path=facts_path,
            cluster_path=cluster_path,
        )
        results.append(
            SuggestionRunAcceptedOut(
                outcome="accepted",
                kind=context.kind,
                key=context.key,
                run_id=run_id,
            )
        )
    return SuggestionRunsOut(results=results)
