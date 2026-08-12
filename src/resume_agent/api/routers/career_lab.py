"""Run-backed Career Lab resources and lifecycle endpoints."""

from __future__ import annotations

import math

from fastapi import APIRouter, Depends, Query, Request
from sqlmodel import Session, col, select

from resume_agent.api.deps import (
    get_career_lab_dir,
    get_engine,
    get_run_manager,
    get_session,
    get_settings_dep,
)
from resume_agent.api.errors import ApiException
from resume_agent.api.runs.conversation import with_conversation_stream
from resume_agent.api.runs.launch import launch
from resume_agent.api.runs.manager import RunManager
from resume_agent.api.schemas.career_lab import (
    CareerLabContextIn,
    CareerLabMessageIn,
    CareerLabSessionOut,
    CareerLabSessionPatchIn,
    CareerLabSessionSummaryOut,
    CareerLabSessionsOut,
    CareerLabSkillOut,
    CareerLabSkillsOut,
    CareerLabStartIn,
)
from resume_agent.api.schemas.base import Pagination
from resume_agent.api.schemas.runs import RunOut
from resume_agent.career_lab.models import CareerLabContextRefs
from resume_agent.career_lab.store import (
    active_session_for_job,
    archive_session,
    delete_session,
    list_sessions,
    rename_session,
    unarchive_session,
)
from resume_agent.career_skills.models import AgentFamily
from resume_agent.career_skills.registry import CareerSkillRegistry, SkillUnavailable
from resume_agent.config import Settings
from resume_agent.llm_runner import missing_model_keys
from resume_agent.tracking.tables import Job
from resume_agent.services.career_lab import (
    run_end_turn,
    run_message_turn,
    run_start_turn,
    session_view,
)

router = APIRouter()


def _root(request: Request):
    return get_career_lab_dir(request)


def _guard_keys(settings: Settings) -> None:
    missing = missing_model_keys(settings)
    if missing:
        raise ApiException(
            400,
            "SETUP_INCOMPLETE",
            f"Missing API key for configured model(s): {', '.join(missing)}",
        )


def _context(payload: CareerLabContextIn | None) -> CareerLabContextRefs:
    if payload is None:
        return CareerLabContextRefs()
    return CareerLabContextRefs.model_validate(payload.model_dump())


def _registry(settings: Settings) -> CareerSkillRegistry:
    return CareerSkillRegistry.from_settings(settings)


def _validate_skill(settings: Settings, skill) -> None:
    if skill is None:
        return
    try:
        _registry(settings).require(
            skill.value,
            family=AgentFamily.CAREER_LAB,
            use="career_lab",
        )
    except SkillUnavailable as exc:
        raise ApiException(409, "CAPABILITY_UNAVAILABLE", str(exc)) from exc


def _value_error(exc: ValueError) -> ApiException:
    message = str(exc)
    if "unknown" in message:
        return ApiException(404, "NOT_FOUND", message)
    if any(
        token in message
        for token in (
            "active Career Lab",
            "session ended",
            "only ended",
            "already archived",
            "not archived",
            "run is active",
        )
    ):
        return ApiException(409, "CONFLICT", message)
    return ApiException(422, "VALIDATION_ERROR", message)


def _active_run(manager: RunManager, session_id: str) -> bool:
    return any(
        snapshot.meta is not None
        and snapshot.meta.get("sessionId") == session_id
        for snapshot in manager.list_active()
    )


def _run_meta(
    *,
    session_id: str | None,
    turn_count: int,
    skill,
    job_id: int | None = None,
) -> dict[str, object]:
    meta: dict[str, object] = {
        "stream": True,
        "turnCount": turn_count,
    }
    if session_id is not None:
        meta["sessionId"] = session_id
    # A start has no session yet, so `jobId` is the only thing that identifies
    # which surface launched it. Without it the Career Lab page adopts a job
    # modal's start as its own recovered run — same shape, no `sessionId`.
    if job_id is not None:
        meta["jobId"] = job_id
    if skill is not None:
        meta["skill"] = skill.value
    return meta


@router.get("/career-lab/skills", response_model=CareerLabSkillsOut)
def list_career_lab_skills(settings: Settings = Depends(get_settings_dep)):
    rows = [
        CareerLabSkillOut.model_validate(capability.model_dump())
        for capability in _registry(settings).public_capabilities()
        if capability.family is AgentFamily.CAREER_LAB
    ]
    return CareerLabSkillsOut(skills=rows)


@router.post("/career-lab/sessions", response_model=RunOut, status_code=202)
def start_career_lab(
    payload: CareerLabStartIn,
    request: Request,
    manager: RunManager = Depends(get_run_manager),
    settings: Settings = Depends(get_settings_dep),
):
    _guard_keys(settings)
    _validate_skill(settings, payload.skill)
    root = _root(request)
    context = _context(payload.context)
    # Scoped to the job this thread will be anchored to, so a thread about one
    # role never blocks starting one about another. `run_start_turn` re-checks
    # the same scope when its worker actually begins.
    current = active_session_for_job(root, context.job_id)
    if current is not None:
        raise ApiException(
            409,
            "SESSION_ACTIVE",
            # Names the scope it actually checked: the bare message read as
            # "you may only ever have one", which is no longer the rule.
            "An active Career Lab session exists for this job"
            if context.job_id is not None
            else "An active Career Lab session exists",
            details={"sessionId": current["session_id"]},
        )
    engine = get_engine(request)
    return launch(
        manager,
        "career-lab-turn",
        with_conversation_stream(
            manager,
            lambda reporter, sink: run_start_turn(
                reporter,
                root=root,
                engine=engine,
                message=payload.message,
                goal=payload.goal,
                skill=payload.skill,
                context_refs=context,
                sink=sink,
                registry=_registry(settings),
                settings=settings,
            ),
        ),
        # Per job, matching the active-session scope: two jobs may open a
        # thread concurrently, the same job may not.
        singleton_key=f"career-lab:start:{context.job_id if context.job_id else '-'}",
        singleton_conflict="raise",
        busy_code="CAREER_LAB_BUSY",
        busy_message="A Career Lab turn is already running",
        meta=_run_meta(
            session_id=None,
            turn_count=0,
            skill=payload.skill,
            job_id=context.job_id,
        ),
    )


@router.post(
    "/career-lab/sessions/{session_id}/messages",
    response_model=RunOut,
    status_code=202,
)
def message_career_lab(
    session_id: str,
    payload: CareerLabMessageIn,
    request: Request,
    manager: RunManager = Depends(get_run_manager),
    settings: Settings = Depends(get_settings_dep),
):
    _guard_keys(settings)
    _validate_skill(settings, payload.skill)
    root = _root(request)
    try:
        current = session_view(root, session_id)
    except ValueError as exc:
        raise _value_error(exc) from exc
    if current["status"] != "active":
        raise ApiException(409, "CONFLICT", "session ended")
    return launch(
        manager,
        "career-lab-turn",
        with_conversation_stream(
            manager,
            lambda reporter, sink: run_message_turn(
                reporter,
                root=root,
                engine=get_engine(request),
                session_id=session_id,
                message=payload.message,
                skill=payload.skill,
                context_refs=_context(payload.context),
                sink=sink,
                registry=_registry(settings),
                settings=settings,
            ),
        ),
        singleton_key=f"career-lab:{session_id}",
        singleton_conflict="raise",
        busy_code="CAREER_LAB_BUSY",
        busy_message="A Career Lab turn is already running",
        meta=_run_meta(
            session_id=session_id,
            turn_count=len(current["turns"]),
            skill=payload.skill,
        ),
    )


@router.post(
    "/career-lab/sessions/{session_id}/end", response_model=RunOut, status_code=202
)
def end_career_lab(
    session_id: str,
    request: Request,
    manager: RunManager = Depends(get_run_manager),
):
    root = _root(request)
    try:
        current = session_view(root, session_id)
    except ValueError as exc:
        raise _value_error(exc) from exc
    if current["status"] != "active":
        raise ApiException(409, "CONFLICT", "session ended")
    return launch(
        manager,
        "career-lab-end",
        lambda reporter: run_end_turn(reporter, root=root, session_id=session_id),
        singleton_key=f"career-lab:{session_id}",
        singleton_conflict="raise",
        busy_code="CAREER_LAB_BUSY",
        busy_message="A Career Lab operation is already running",
        meta=_run_meta(session_id=session_id, turn_count=len(current["turns"]), skill=None),
    )


def _ordered_for_listing(rows: list[dict]) -> list[dict]:
    """Open threads first, then most recently started.

    Page 1 therefore always holds every active thread, which is what makes a
    job's Career Lab tab correct without paging: it decides whether to offer
    "start a thread" from that page alone, and an active thread stranded on
    page 2 offered a Start that the API then rejected with a 409. The substrate
    lists oldest-first, which is the wrong end for a history rail anyway.

    Two stable passes rather than one composite key, because the two components
    sort in opposite directions and `started_at` is a string that cannot be
    negated.
    """
    ordered = sorted(rows, key=lambda row: row["started_at"], reverse=True)
    ordered.sort(key=lambda row: 0 if row["status"] == "active" else 1)
    return ordered


def _job_labels(session, job_ids: set[int]) -> dict[int, tuple[str | None, str | None]]:
    """Company and title for the anchored jobs on this page, in one query."""
    if not job_ids:
        return {}
    rows = session.exec(
        select(Job.id, Job.company, Job.title).where(col(Job.id).in_(job_ids))
    ).all()
    return {row[0]: (row[1], row[2]) for row in rows}


def _job_label(
    labels: dict[int, tuple[str | None, str | None]], job_id: object
) -> tuple[str | None, str | None]:
    """Resolve a row's untyped optional anchor without passing ``None`` to ``dict.get``."""
    if not isinstance(job_id, int):
        return (None, None)
    return labels.get(job_id, (None, None))


@router.get("/career-lab/sessions", response_model=CareerLabSessionsOut)
def list_career_lab_sessions(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, alias="pageSize", ge=1, le=100),
    include_archived: bool = Query(False, alias="includeArchived"),
    job_id: int | None = Query(None, alias="jobId", ge=1),
    session: Session = Depends(get_session),
):
    rows = _ordered_for_listing(
        list_sessions(_root(request), job_id=job_id, include_archived=include_archived)
    )
    total = len(rows)
    start = (page - 1) * page_size
    selected = rows[start : start + page_size]
    # Resolved once for the page, then handed to the projections — never a
    # lookup per row.
    labels = _job_labels(
        session, {row["job_id"] for row in selected if row.get("job_id")}
    )
    return CareerLabSessionsOut(
        sessions=[
            CareerLabSessionSummaryOut(
                session_id=row["session_id"],
                title=row.get("title", ""),
                goal=row["goal"],
                started_at=row["started_at"],
                ended_at=row.get("ended_at"),
                status=row["status"],
                archived_at=row.get("archived_at"),
                job_id=row.get("job_id"),
                job_company=_job_label(labels, row.get("job_id"))[0],
                job_title=_job_label(labels, row.get("job_id"))[1],
                turn_count=len(row["turns"]),
            )
            for row in selected
        ],
        pagination=Pagination(
            page=page,
            page_size=page_size,
            total_items=total,
            total_pages=math.ceil(total / page_size) if total else 0,
        ),
    )


@router.get("/career-lab/sessions/{session_id}", response_model=CareerLabSessionOut)
def get_career_lab_session(session_id: str, request: Request):
    try:
        return CareerLabSessionOut.model_validate(session_view(_root(request), session_id))
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.patch("/career-lab/sessions/{session_id}", response_model=CareerLabSessionOut)
def rename_career_lab_session(
    session_id: str,
    payload: CareerLabSessionPatchIn,
    request: Request,
    manager: RunManager = Depends(get_run_manager),
):
    _ensure_no_active_run(manager, session_id)
    try:
        rename_session(_root(request), session_id, payload.title)
        return CareerLabSessionOut.model_validate(session_view(_root(request), session_id))
    except ValueError as exc:
        raise _value_error(exc) from exc

def _ensure_no_active_run(manager: RunManager, session_id: str) -> None:
    if _active_run(manager, session_id):
        raise ApiException(409, "CAREER_LAB_BUSY", "A Career Lab run is active")


@router.post(
    "/career-lab/sessions/{session_id}/archive", response_model=CareerLabSessionOut
)
def archive_career_lab(
    session_id: str,
    request: Request,
    manager: RunManager = Depends(get_run_manager),
):
    _ensure_no_active_run(manager, session_id)
    try:
        archive_session(_root(request), session_id)
        return CareerLabSessionOut.model_validate(session_view(_root(request), session_id))
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.post(
    "/career-lab/sessions/{session_id}/unarchive",
    response_model=CareerLabSessionOut,
)
def unarchive_career_lab(
    session_id: str,
    request: Request,
    manager: RunManager = Depends(get_run_manager),
):
    _ensure_no_active_run(manager, session_id)
    try:
        unarchive_session(_root(request), session_id)
        return CareerLabSessionOut.model_validate(session_view(_root(request), session_id))
    except ValueError as exc:
        raise _value_error(exc) from exc


@router.delete("/career-lab/sessions/{session_id}", status_code=204)
def delete_career_lab(
    session_id: str,
    request: Request,
    manager: RunManager = Depends(get_run_manager),
) -> None:
    _ensure_no_active_run(manager, session_id)
    try:
        delete_session(_root(request), session_id)
    except ValueError as exc:
        raise _value_error(exc) from exc
