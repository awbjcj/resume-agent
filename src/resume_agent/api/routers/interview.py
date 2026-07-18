"""Mock interview endpoints: run-backed turns over durable session files."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlmodel import Session

from resume_agent.api.deps import (
    get_interview_dir,
    get_run_manager,
    get_session,
    get_settings_dep,
)
from resume_agent.api.errors import ApiException
from resume_agent.api.runs.manager import (
    RunManager,
    RunQuotaError,
    RunResetConflict,
    RunSingletonConflict,
)
from resume_agent.api.runs.sse import record_to_run
from resume_agent.api.schemas.interview import (
    InterviewMessageIn,
    InterviewSessionOut,
    InterviewSessionsOut,
    InterviewStartIn,
)
from resume_agent.api.schemas.runs import RunOut
from resume_agent.config import Settings
from resume_agent.interview.store import active_session
from resume_agent.llm_runner import resolve_api_key
from resume_agent.services.mock_interview import (
    run_answer_turn,
    run_debrief_turn,
    run_opening_turn,
    session_view,
    sessions_view,
)
from resume_agent.tracking.tables import Job, ResumeVersion

router = APIRouter()
_SINGLETON = "mock-interview"


def _guard_keys(settings: Settings) -> None:
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


def _submit(manager: RunManager, kind: str, work) -> RunOut:
    try:
        run_id = manager.submit(
            kind, work, singleton_key=_SINGLETON, singleton_conflict="raise"
        )
    except RunSingletonConflict as exc:
        raise ApiException(
            409,
            "INTERVIEW_BUSY",
            "An interview turn is already running",
            details={"runId": exc.run_id},
        ) from exc
    except RunResetConflict as exc:
        raise ApiException(409, exc.code, str(exc)) from exc
    except RunQuotaError as exc:
        raise ApiException(429, exc.code, str(exc)) from exc
    record = manager.get(run_id)
    assert record is not None
    return record_to_run(record)


def _value_error(exc: ValueError) -> ApiException:
    message = str(exc)
    if "unknown" in message:
        return ApiException(404, "NOT_FOUND", message)
    if any(token in message for token in ("session ended", "active session", "concluded")):
        return ApiException(409, "CONFLICT", message)
    return ApiException(422, "VALIDATION_ERROR", message)


@router.post("/interview/sessions", response_model=RunOut, status_code=202)
def start_interview(
    payload: InterviewStartIn,
    request: Request,
    manager: RunManager = Depends(get_run_manager),
    settings: Settings = Depends(get_settings_dep),
    db: Session = Depends(get_session),
):
    _guard_keys(settings)
    interview_dir = get_interview_dir(request)
    if active_session(interview_dir) is not None:
        raise ApiException(409, "SESSION_ACTIVE", "An active interview session exists")
    job = db.get(Job, payload.job_id)
    if job is None:
        raise ApiException(404, "NOT_FOUND", f"unknown job: {payload.job_id}")
    if not job.jd_text.strip():
        raise ApiException(422, "VALIDATION_ERROR", "job has no description")
    version = db.get(ResumeVersion, payload.resume_version_id)
    if version is None or version.job_id != payload.job_id:
        raise ApiException(
            422, "VALIDATION_ERROR", f"unknown resume version: {payload.resume_version_id}"
        )
    engine = request.app.state.engine
    style = payload.style.model_dump()
    return _submit(
        manager,
        "mock-interview-open",
        lambda reporter: run_opening_turn(
            reporter,
            interview_dir=interview_dir,
            engine=engine,
            job_id=payload.job_id,
            resume_version_id=payload.resume_version_id,
            style=style,
        ),
    )


@router.post(
    "/interview/sessions/{session_id}/messages", response_model=RunOut, status_code=202
)
def send_answer(
    session_id: str,
    payload: InterviewMessageIn,
    request: Request,
    manager: RunManager = Depends(get_run_manager),
    settings: Settings = Depends(get_settings_dep),
):
    _guard_keys(settings)
    interview_dir = get_interview_dir(request)
    try:
        view = session_view(interview_dir, session_id)
    except ValueError as exc:
        raise _value_error(exc) from exc
    if view["status"] != "active":
        raise ApiException(409, "CONFLICT", "session ended")
    if view["concluded"]:
        raise ApiException(409, "CONFLICT", "interview concluded; end the session for your debrief")
    return _submit(
        manager,
        "mock-interview-turn",
        lambda reporter: run_answer_turn(
            reporter,
            interview_dir=interview_dir,
            session_id=session_id,
            message=payload.message,
        ),
    )


@router.post(
    "/interview/sessions/{session_id}/end", response_model=RunOut, status_code=202
)
def end_interview(
    session_id: str,
    request: Request,
    manager: RunManager = Depends(get_run_manager),
    settings: Settings = Depends(get_settings_dep),
):
    _guard_keys(settings)
    interview_dir = get_interview_dir(request)
    try:
        view = session_view(interview_dir, session_id)
    except ValueError as exc:
        raise _value_error(exc) from exc
    if view["status"] != "active":
        raise ApiException(409, "CONFLICT", "session ended")
    return _submit(
        manager,
        "mock-interview-end",
        lambda reporter: run_debrief_turn(
            reporter, interview_dir=interview_dir, session_id=session_id
        ),
    )


@router.get("/interview/sessions", response_model=InterviewSessionsOut)
def list_interview_sessions(
    request: Request, job_id: int | None = Query(None, alias="jobId")
):
    return InterviewSessionsOut.model_validate(
        sessions_view(get_interview_dir(request), job_id=job_id)
    )


@router.get("/interview/sessions/{session_id}", response_model=InterviewSessionOut)
def get_interview_session(session_id: str, request: Request):
    try:
        return InterviewSessionOut.model_validate(
            session_view(get_interview_dir(request), session_id)
        )
    except ValueError as exc:
        raise _value_error(exc) from exc
