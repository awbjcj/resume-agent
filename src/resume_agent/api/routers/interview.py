"""Mock interview endpoints: run-backed turns over durable session files."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlmodel import Session

from resume_agent.api.deps import (
    get_interview_dir,
    get_run_manager,
    get_session,
    get_settings_dep,
)
from resume_agent.api.errors import ApiException
from resume_agent.api.runs.conversation import with_conversation_stream
from resume_agent.api.runs.launch import launch
from resume_agent.api.runs.manager import RunManager
from resume_agent.api.schemas.interview import (
    InterviewMessageIn,
    InterviewSessionOut,
    InterviewSessionsOut,
    InterviewStartIn,
)
from resume_agent.api.schemas.runs import RunOut
from resume_agent.config import Settings
from resume_agent.interview.store import (
    active_session_for_job,
    archive_session,
    delete_session,
    unarchive_session,
)
from resume_agent.llm_runner import missing_model_keys
from resume_agent.services.mock_interview import (
    run_answer_turn,
    run_debrief_turn,
    run_opening_turn,
    session_view,
    sessions_view,
)
from resume_agent.tracking.tables import Job, ResumeVersion

router = APIRouter()
def _guard_keys(settings: Settings) -> None:
    missing = missing_model_keys(settings)
    if missing:
        raise ApiException(
            400,
            "SETUP_INCOMPLETE",
            f"Missing API key for configured model(s): {', '.join(missing)}",
        )


def _submit(
    manager: RunManager,
    kind: str,
    work,
    *,
    singleton: str,
    streaming: bool = True,
    meta: dict[str, object] | None = None,
) -> RunOut:
    return launch(
        manager,
        kind,
        with_conversation_stream(manager, work) if streaming else work,
        singleton_key=singleton,
        singleton_conflict="raise",
        busy_code="INTERVIEW_BUSY",
        busy_message="An interview turn is already running",
        meta=meta,
    )


def _value_error(exc: ValueError) -> ApiException:
    message = str(exc)
    if "unknown" in message:
        return ApiException(404, "NOT_FOUND", message)
    if any(
        token in message
        for token in (
            "session ended",
            "active session",
            "concluded",
            "archived",
            "only ended",
        )
    ):
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
    existing = active_session_for_job(interview_dir, payload.job_id)
    if existing is not None:
        raise ApiException(
            409,
            "SESSION_ACTIVE_FOR_JOB",
            "An active interview session already exists for this job",
            details={"sessionId": existing["session_id"]},
        )
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
        lambda reporter, sink: run_opening_turn(
            reporter,
            interview_dir=interview_dir,
            engine=engine,
            job_id=payload.job_id,
            resume_version_id=payload.resume_version_id,
            style=style,
            sink=sink,
        ),
        singleton=f"mock-interview-open:{payload.job_id}",
        meta={"stream": True, "jobId": payload.job_id},
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
        lambda reporter, sink: run_answer_turn(
            reporter,
            interview_dir=interview_dir,
            session_id=session_id,
            message=payload.message,
            sink=sink,
        ),
        singleton=f"mock-interview:{session_id}",
        meta={
            "stream": True,
            "sessionId": session_id,
            "turnCount": len(view["turns"]),
        },
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
        singleton=f"mock-interview:{session_id}",
        streaming=False,
        meta={"stream": False, "sessionId": session_id},
    )


@router.get("/interview/sessions", response_model=InterviewSessionsOut)
def list_interview_sessions(
    request: Request,
    job_id: int | None = Query(None, alias="jobId"),
    include_archived: bool = Query(False, alias="includeArchived"),
    status: Literal["active", "ended"] | None = Query(None),
):
    return InterviewSessionsOut.model_validate(
        sessions_view(
            get_interview_dir(request),
            job_id=job_id,
            include_archived=include_archived,
            status=status,
        )
    )


@router.post(
    "/interview/sessions/{session_id}/archive",
    response_model=InterviewSessionOut,
)
def archive_interview_session(session_id: str, request: Request):
    interview_dir = get_interview_dir(request)
    try:
        archive_session(interview_dir, session_id)
        return InterviewSessionOut.model_validate(
            session_view(interview_dir, session_id)
        )
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.post(
    "/interview/sessions/{session_id}/unarchive",
    response_model=InterviewSessionOut,
)
def unarchive_interview_session(session_id: str, request: Request):
    interview_dir = get_interview_dir(request)
    try:
        unarchive_session(interview_dir, session_id)
        return InterviewSessionOut.model_validate(
            session_view(interview_dir, session_id)
        )
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.delete("/interview/sessions/{session_id}", status_code=204)
def delete_interview_session(session_id: str, request: Request) -> None:
    try:
        delete_session(get_interview_dir(request), session_id)
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.get("/interview/sessions/{session_id}", response_model=InterviewSessionOut)
def get_interview_session(session_id: str, request: Request):
    try:
        return InterviewSessionOut.model_validate(
            session_view(get_interview_dir(request), session_id)
        )
    except ValueError as exc:
        raise _value_error(exc) from exc
