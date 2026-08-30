from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from resume_agent.api.deps import get_session
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.run_completions import (
    RunCompletionOut,
    RunCompletionsReadOut,
)
from resume_agent.services.run_completions import (
    list_run_completions,
    mark_all_run_completions_read,
    mark_run_completion_read,
)

router = APIRouter()


@router.get("/run-completions", response_model=list[RunCompletionOut])
def list_completions(
    limit: int = Query(default=50, ge=1, le=100),
    unread_only: bool = Query(default=False),
    session: Session = Depends(get_session),
):
    return list_run_completions(session, limit=limit, unread_only=unread_only)


@router.post("/run-completions/{completion_id}/read", response_model=RunCompletionOut)
def mark_read(completion_id: int, session: Session = Depends(get_session)):
    row = mark_run_completion_read(session, completion_id)
    if row is None:
        raise ApiException(
            404, "NOT_FOUND", f"Run completion #{completion_id} not found"
        )
    return row


@router.post("/run-completions/read-all", response_model=RunCompletionsReadOut)
def mark_all_read(session: Session = Depends(get_session)):
    return RunCompletionsReadOut(
        marked_read=mark_all_run_completions_read(session)
    )
