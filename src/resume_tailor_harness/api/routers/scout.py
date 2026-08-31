"""Discovery Scout endpoints: streamed turns and deterministic decisions."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.engine import Engine
from sqlmodel import Session

from resume_tailor_harness.api.deps import (
    get_config_store,
    get_engine,
    get_profile_dir,
    get_run_manager,
    get_scout_dir,
    get_settings_dep,
)
from resume_tailor_harness.api.errors import ApiException
from resume_tailor_harness.api.runs.conversation import with_conversation_stream
from resume_tailor_harness.api.runs.launch import launch, session_work
from resume_tailor_harness.api.runs.manager import RunManager
from resume_tailor_harness.api.schemas.runs import RunOut
from resume_tailor_harness.api.schemas.scout import (
    ScoutApproveIn,
    ScoutDismissIn,
    ScoutMessageIn,
    ScoutResolveSourceIn,
    ScoutSessionOut,
    ScoutSessionPatchIn,
    ScoutSessionsOut,
)
from resume_tailor_harness.config import Settings
from resume_tailor_harness.discovery.scout_store import (
    ScoutProposalChangedError,
    active_session,
    archive_session,
    delete_session,
    rename_session,
    unarchive_session,
)
from resume_tailor_harness.llm_runner import missing_model_keys, plan_search
from resume_tailor_harness.services.scout import (
    approve_proposal,
    dismiss_proposal,
    run_message_turn,
    run_recap_turn,
    run_start_turn,
    resolve_proposal_source,
    session_view,
    sessions_view,
)
from resume_tailor_harness.services.scout_intelligence import ScoutCompanyIntelligenceLookup

router = APIRouter()
_SINGLETON = "scout"
_RUN_KINDS = frozenset({"scout-start", "scout-turn", "scout-end"})


def _workspace_root(request: Request):
    return get_scout_dir(request).parent


def _config_paths(request: Request) -> tuple[str, str]:
    config_dir = get_config_store(request).config_dir
    return str(config_dir / "connectors.yaml"), str(config_dir / "search.yaml")


def _intelligence_lookup(session: Session) -> ScoutCompanyIntelligenceLookup:
    return ScoutCompanyIntelligenceLookup(session)


def _guard_setup(settings: Settings) -> None:
    missing = missing_model_keys(settings)
    if missing:
        raise ApiException(
            400,
            "SETUP_INCOMPLETE",
            f"Missing API key for configured model(s): {', '.join(missing)}",
        )
    try:
        search = plan_search(settings.mid_model, settings.search_mode)
    except ValueError as exc:
        raise ApiException(400, "SEARCH_DISABLED", str(exc)) from exc
    if search.strategy == "none":
        raise ApiException(
            400,
            "SEARCH_DISABLED",
            "Discovery Scout needs web search; change search_mode from off.",
        )


def _submit(
    manager: RunManager,
    engine: Engine,
    kind: str,
    work,
    *,
    session_id: str,
    turn_count: int,
) -> RunOut:
    def run_with_session(session: Session, reporter):
        return with_conversation_stream(
            manager,
            lambda current_reporter, sink: work(session, current_reporter, sink),
        )(reporter)

    return launch(
        manager,
        kind,
        session_work(engine, run_with_session),
        singleton_key=_SINGLETON,
        singleton_conflict="raise",
        busy_code="SCOUT_BUSY",
        busy_message="A Discovery Scout turn is already running",
        meta={"stream": True, "sessionId": session_id, "turnCount": turn_count},
    )


def _value_error(exc: ValueError) -> ApiException:
    message = str(exc)
    if "unknown" in message:
        return ApiException(404, "NOT_FOUND", message)
    if any(
        token in message
        for token in (
            "already resolved",
            "not approvable",
            "manual confirmation required",
            "requires a local browser",
            "session ended",
            "active session",
            "archived",
            "only ended",
        )
    ):
        return ApiException(409, "CONFLICT", message)
    return ApiException(422, "VALIDATION_ERROR", message)


def _session_run_active(manager: RunManager, session_id: str) -> bool:
    return any(
        run.kind in _RUN_KINDS
        and run.meta is not None
        and run.meta.get("sessionId") == session_id
        for run in manager.list_active()
    )


def _guard_lifecycle_idle(manager: RunManager, session_id: str) -> None:
    if _session_run_active(manager, session_id):
        raise ApiException(
            409, "SCOUT_BUSY", "A Discovery Scout turn is already running"
        )


@router.post("/scout/sessions", response_model=RunOut, status_code=202)
def start_session(
    payload: ScoutMessageIn,
    request: Request,
    manager: RunManager = Depends(get_run_manager),
    settings: Settings = Depends(get_settings_dep),
):
    _guard_setup(settings)
    workspace_root = _workspace_root(request)
    if active_session(workspace_root) is not None:
        raise ApiException(409, "SESSION_ACTIVE", "An active Scout session exists")
    session_id = uuid.uuid4().hex
    connectors_path, search_path = _config_paths(request)
    engine = get_engine(request)
    return _submit(
        manager,
        engine,
        "scout-start",
        lambda session, reporter, sink: run_start_turn(
            reporter,
            workspace_root=workspace_root,
            session_id=session_id,
            message=payload.message,
            connectors_path=connectors_path,
            search_path=search_path,
            profile_dir=get_profile_dir(request),
            browser_enabled=settings.browser_enabled,
            sink=sink,
            company_intelligence_lookup=_intelligence_lookup(session),
        ),
        session_id=session_id,
        turn_count=0,
    )


@router.post(
    "/scout/sessions/{session_id}/messages",
    response_model=RunOut,
    status_code=202,
)
def send_message(
    session_id: str,
    payload: ScoutMessageIn,
    request: Request,
    manager: RunManager = Depends(get_run_manager),
    settings: Settings = Depends(get_settings_dep),
):
    workspace_root = _workspace_root(request)
    try:
        current = session_view(
            workspace_root, session_id, browser_enabled=settings.browser_enabled
        )
    except ValueError as exc:
        raise _value_error(exc) from exc
    if current["status"] != "active":
        raise ApiException(409, "CONFLICT", "session ended")
    _guard_setup(settings)
    connectors_path, search_path = _config_paths(request)
    engine = get_engine(request)
    return _submit(
        manager,
        engine,
        "scout-turn",
        lambda session, reporter, sink: run_message_turn(
            reporter,
            workspace_root=workspace_root,
            session_id=session_id,
            message=payload.message,
            connectors_path=connectors_path,
            search_path=search_path,
            profile_dir=get_profile_dir(request),
            browser_enabled=settings.browser_enabled,
            sink=sink,
            company_intelligence_lookup=_intelligence_lookup(session),
        ),
        session_id=session_id,
        turn_count=len(current["turns"]),
    )


@router.post("/scout/sessions/{session_id}/end", response_model=RunOut, status_code=202)
def end_scout_session(
    session_id: str,
    request: Request,
    manager: RunManager = Depends(get_run_manager),
    settings: Settings = Depends(get_settings_dep),
):
    _guard_setup(settings)
    workspace_root = _workspace_root(request)
    try:
        current = session_view(
            workspace_root, session_id, browser_enabled=settings.browser_enabled
        )
    except ValueError as exc:
        raise _value_error(exc) from exc
    if current["status"] != "active":
        raise ApiException(409, "CONFLICT", "session ended")
    connectors_path, search_path = _config_paths(request)
    engine = get_engine(request)
    return _submit(
        manager,
        engine,
        "scout-end",
        lambda session, reporter, sink: run_recap_turn(
            reporter,
            workspace_root=workspace_root,
            session_id=session_id,
            connectors_path=connectors_path,
            search_path=search_path,
            profile_dir=get_profile_dir(request),
            browser_enabled=settings.browser_enabled,
            sink=sink,
            company_intelligence_lookup=_intelligence_lookup(session),
        ),
        session_id=session_id,
        turn_count=len(current["turns"]),
    )


@router.post(
    "/scout/sessions/{session_id}/proposals/{proposal_id}/approve",
    response_model=ScoutSessionOut,
)
def approve_scout_proposal(
    session_id: str,
    proposal_id: str,
    request: Request,
    payload: ScoutApproveIn | None = None,
    settings: Settings = Depends(get_settings_dep),
):
    connectors_path, search_path = _config_paths(request)
    try:
        return ScoutSessionOut.model_validate(
            approve_proposal(
                _workspace_root(request),
                session_id,
                proposal_id,
                config_store=get_config_store(request),
                connectors_path=connectors_path,
                search_path=search_path,
                browser_enabled=settings.browser_enabled,
                manual_confirmation=payload.manual_confirmation if payload else False,
            )
        )
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.post(
    "/scout/sessions/{session_id}/proposals/{proposal_id}/resolve",
    response_model=ScoutSessionOut,
)
def resolve_scout_proposal(
    session_id: str,
    proposal_id: str,
    payload: ScoutResolveSourceIn,
    request: Request,
    settings: Settings = Depends(get_settings_dep),
):
    _, search_path = _config_paths(request)
    try:
        return ScoutSessionOut.model_validate(
            resolve_proposal_source(
                _workspace_root(request),
                session_id,
                proposal_id,
                url=str(payload.url),
                search_path=search_path,
                browser_enabled=settings.browser_enabled,
            )
        )
    except ScoutProposalChangedError as exc:
        raise ApiException(409, "CONFLICT", str(exc)) from exc
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.post(
    "/scout/sessions/{session_id}/proposals/{proposal_id}/dismiss",
    response_model=ScoutSessionOut,
)
def dismiss_scout_proposal(
    session_id: str,
    proposal_id: str,
    payload: ScoutDismissIn,
    request: Request,
    settings: Settings = Depends(get_settings_dep),
):
    try:
        return ScoutSessionOut.model_validate(
            dismiss_proposal(
                _workspace_root(request),
                session_id,
                proposal_id,
                reason=payload.reason,
                browser_enabled=settings.browser_enabled,
            )
        )
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.get("/scout/sessions", response_model=ScoutSessionsOut)
def list_scout_sessions(
    request: Request,
    include_archived: bool = Query(False, alias="includeArchived"),
    status: Literal["active", "ended"] | None = Query(None),
):
    return ScoutSessionsOut.model_validate(
        sessions_view(
            _workspace_root(request),
            include_archived=include_archived,
            status=status,
        )
    )


@router.get("/scout/sessions/{session_id}", response_model=ScoutSessionOut)
def get_scout_session(
    session_id: str,
    request: Request,
    settings: Settings = Depends(get_settings_dep),
):
    try:
        return ScoutSessionOut.model_validate(
            session_view(
                _workspace_root(request),
                session_id,
                browser_enabled=settings.browser_enabled,
            )
        )
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.post("/scout/sessions/{session_id}/archive", response_model=ScoutSessionOut)
def archive_scout_session(
    session_id: str,
    request: Request,
    manager: RunManager = Depends(get_run_manager),
    settings: Settings = Depends(get_settings_dep),
):
    _guard_lifecycle_idle(manager, session_id)
    try:
        archive_session(_workspace_root(request), session_id)
        return ScoutSessionOut.model_validate(
            session_view(
                _workspace_root(request),
                session_id,
                browser_enabled=settings.browser_enabled,
            )
        )
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.patch("/scout/sessions/{session_id}", response_model=ScoutSessionOut)
def rename_scout_session(
    session_id: str,
    payload: ScoutSessionPatchIn,
    request: Request,
    manager: RunManager = Depends(get_run_manager),
    settings: Settings = Depends(get_settings_dep),
):
    _guard_lifecycle_idle(manager, session_id)
    try:
        rename_session(_workspace_root(request), session_id, payload.title)
        return ScoutSessionOut.model_validate(
            session_view(
                _workspace_root(request),
                session_id,
                browser_enabled=settings.browser_enabled,
            )
        )
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.post("/scout/sessions/{session_id}/unarchive", response_model=ScoutSessionOut)
def unarchive_scout_session(
    session_id: str,
    request: Request,
    manager: RunManager = Depends(get_run_manager),
    settings: Settings = Depends(get_settings_dep),
):
    _guard_lifecycle_idle(manager, session_id)
    try:
        unarchive_session(_workspace_root(request), session_id)
        return ScoutSessionOut.model_validate(
            session_view(
                _workspace_root(request),
                session_id,
                browser_enabled=settings.browser_enabled,
            )
        )
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.delete("/scout/sessions/{session_id}", status_code=204)
def delete_scout_session(
    session_id: str,
    request: Request,
    manager: RunManager = Depends(get_run_manager),
) -> None:
    _guard_lifecycle_idle(manager, session_id)
    try:
        delete_session(_workspace_root(request), session_id)
    except ValueError as exc:
        raise _value_error(exc) from exc
