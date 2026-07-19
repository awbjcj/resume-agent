"""Profile Coach endpoints: run-backed turns and deterministic note approval."""

from __future__ import annotations

from typing import Literal, cast

from fastapi import APIRouter, Depends, Query, Request

from resume_agent.api.deps import (
    get_config_store,
    get_profile_dir,
    get_run_manager,
    get_settings_dep,
)
from resume_agent.api.errors import ApiException
from resume_agent.api.runs.launch import launch
from resume_agent.api.runs.manager import (
    RunManager,
    RunQuotaError,
    RunResetConflict,
    RunSingletonConflict,
)
from resume_agent.api.schemas.coach import (
    CoachEndIn,
    CoachMessageIn,
    CoachNoteIn,
    CoachNoteOut,
    CoachSessionOut,
    CoachSessionsOut,
)
from resume_agent.api.schemas.config import ProfileConfigDoc
from resume_agent.api.schemas.runs import RunOut
from resume_agent.config import Settings
from resume_agent.llm_runner import resolve_api_key
from resume_agent.profile.coach_store import (
    active_session,
    archive_session,
    delete_session,
    unarchive_session,
)
from resume_agent.profile.corpus import load_manifest
from resume_agent.services.profile_coach import (
    approve_draft,
    discard_draft,
    run_build_with_impact,
    run_message_turn,
    run_opening_turn,
    run_recap_turn,
    session_view,
    sessions_view,
)

router = APIRouter()
_SINGLETON = "profile-coach"


def _guard_setup(request: Request, settings: Settings):
    profile_dir = get_profile_dir(request)
    if not any(
        doc.primary and doc.mode == "literal" for doc in load_manifest(profile_dir).docs
    ):
        raise ApiException(
            400,
            "SETUP_INCOMPLETE",
            "Upload a primary resume before coaching",
        )
    configured = (("mid", settings.mid_model), ("cheap", settings.cheap_model))
    missing = [
        f"{tier} ({model})" for tier, model in configured if not resolve_api_key(model)
    ]
    if missing:
        raise ApiException(
            400,
            "SETUP_INCOMPLETE",
            f"Missing API key for configured model(s): {', '.join(missing)}",
        )
    return profile_dir


def _submit(manager: RunManager, kind: str, work) -> RunOut:
    return launch(
        manager,
        kind,
        work,
        singleton_key=_SINGLETON,
        singleton_conflict="raise",
        busy_code="COACH_BUSY",
        busy_message="A coach turn is already running",
    )


def _value_error(exc: ValueError) -> ApiException:
    message = str(exc)
    if "unknown" in message:
        return ApiException(404, "NOT_FOUND", message)
    if any(
        token in message
        for token in (
            "already resolved",
            "session ended",
            "active session",
            "archived",
            "only ended",
        )
    ):
        return ApiException(409, "CONFLICT", message)
    return ApiException(422, "VALIDATION_ERROR", message)


@router.post("/profile/coach/sessions", response_model=RunOut, status_code=202)
def start_session(
    request: Request,
    manager: RunManager = Depends(get_run_manager),
    settings: Settings = Depends(get_settings_dep),
):
    profile_dir = _guard_setup(request, settings)
    if active_session(profile_dir) is not None:
        raise ApiException(409, "SESSION_ACTIVE", "An active coach session exists")
    engine = request.app.state.engine
    return _submit(
        manager,
        "profile-coach-open",
        lambda reporter: run_opening_turn(
            reporter,
            profile_dir=profile_dir,
            engine=engine,
        ),
    )


@router.post(
    "/profile/coach/sessions/{session_id}/messages",
    response_model=RunOut,
    status_code=202,
)
def send_message(
    session_id: str,
    payload: CoachMessageIn,
    request: Request,
    manager: RunManager = Depends(get_run_manager),
    settings: Settings = Depends(get_settings_dep),
):
    profile_dir = _guard_setup(request, settings)
    try:
        view = session_view(profile_dir, session_id)
    except ValueError as exc:
        raise _value_error(exc) from exc
    if view["status"] != "active":
        raise ApiException(409, "CONFLICT", "session ended")
    engine = request.app.state.engine
    return _submit(
        manager,
        "profile-coach-turn",
        lambda reporter: run_message_turn(
            reporter,
            profile_dir=profile_dir,
            session_id=session_id,
            message=payload.message,
            engine=engine,
        ),
    )


@router.post(
    "/profile/coach/sessions/{session_id}/notes/{topic_id}",
    response_model=CoachNoteOut,
)
def save_note(
    session_id: str,
    topic_id: str,
    payload: CoachNoteIn,
    request: Request,
):
    try:
        doc_id = approve_draft(
            get_profile_dir(request),
            session_id,
            topic_id,
            title=payload.title,
            summary=payload.summary,
            quotes=payload.quotes,
        )
    except ValueError as exc:
        raise _value_error(exc) from exc
    return CoachNoteOut(doc_id=doc_id)


@router.delete(
    "/profile/coach/sessions/{session_id}/notes/{topic_id}",
    response_model=CoachSessionOut,
)
def discard_note(session_id: str, topic_id: str, request: Request):
    profile_dir = get_profile_dir(request)
    try:
        discard_draft(profile_dir, session_id, topic_id)
        return CoachSessionOut.model_validate(session_view(profile_dir, session_id))
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.post(
    "/profile/coach/sessions/{session_id}/end",
    response_model=RunOut,
    status_code=202,
)
def end_coach_session(
    session_id: str,
    payload: CoachEndIn,
    request: Request,
    manager: RunManager = Depends(get_run_manager),
    settings: Settings = Depends(get_settings_dep),
):
    profile_dir = _guard_setup(request, settings)
    try:
        current = session_view(profile_dir, session_id)
    except ValueError as exc:
        raise _value_error(exc) from exc
    if current["status"] != "active":
        raise ApiException(409, "CONFLICT", "session ended")
    profile_config = cast(ProfileConfigDoc, get_config_store(request).get("profile"))
    facts_out = profile_dir / "facts.json"

    def work(reporter):
        ended = run_recap_turn(reporter, profile_dir=profile_dir, session_id=session_id)
        saved_count = sum(
            draft["status"] == "saved" for draft in ended["draftNotes"]
        )
        build_run_id = None
        skipped_reason = None
        if payload.build and saved_count:
            try:
                build_run_id = manager.submit(
                    "profile-build",
                    lambda build_reporter: run_build_with_impact(
                        build_reporter,
                        profile_dir=profile_dir,
                        session_id=session_id,
                        facts_out=facts_out,
                        github_username=profile_config.github_username,
                        github_allow=tuple(profile_config.github_repo_allow),
                        github_deny=tuple(profile_config.github_repo_deny),
                        github_limit=profile_config.github_repo_limit,
                    ),
                    singleton_key="profile-build",
                    singleton_conflict="raise",
                )
            except (RunSingletonConflict, RunResetConflict, RunQuotaError) as exc:
                skipped_reason = str(exc)
        elif not payload.build:
            skipped_reason = "build=false"
        else:
            skipped_reason = "no saved notes to build from"
        return {
            "session": ended,
            "buildRunId": build_run_id,
            "buildSkippedReason": skipped_reason,
        }

    return _submit(manager, "profile-coach-end", work)


@router.get("/profile/coach/sessions", response_model=CoachSessionsOut)
def list_coach_sessions(
    request: Request,
    include_archived: bool = Query(False, alias="includeArchived"),
    status: Literal["active", "ended"] | None = Query(None),
):
    return CoachSessionsOut.model_validate(
        sessions_view(
            get_profile_dir(request),
            include_archived=include_archived,
            status=status,
        )
    )


@router.post(
    "/profile/coach/sessions/{session_id}/archive",
    response_model=CoachSessionOut,
)
def archive_coach_session(session_id: str, request: Request):
    profile_dir = get_profile_dir(request)
    try:
        archive_session(profile_dir, session_id)
        return CoachSessionOut.model_validate(session_view(profile_dir, session_id))
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.post(
    "/profile/coach/sessions/{session_id}/unarchive",
    response_model=CoachSessionOut,
)
def unarchive_coach_session(session_id: str, request: Request):
    profile_dir = get_profile_dir(request)
    try:
        unarchive_session(profile_dir, session_id)
        return CoachSessionOut.model_validate(session_view(profile_dir, session_id))
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.delete("/profile/coach/sessions/{session_id}", status_code=204)
def delete_coach_session(session_id: str, request: Request) -> None:
    try:
        delete_session(get_profile_dir(request), session_id)
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.get("/profile/coach/sessions/{session_id}", response_model=CoachSessionOut)
def get_coach_session(session_id: str, request: Request):
    try:
        return CoachSessionOut.model_validate(
            session_view(get_profile_dir(request), session_id)
        )
    except ValueError as exc:
        raise _value_error(exc) from exc
