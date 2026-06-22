"""Read-only board lists: shortlist, pipeline, triage. Paginated + core filters."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from resume_agent.api.deps import get_session
from resume_agent.api.mappers import to_page
from resume_agent.api.schemas.base import Page
from resume_agent.api.schemas.jobs import PipelineItem, ShortlistItem, TriageItem
from resume_agent.services import board

router = APIRouter()


@router.get("/shortlist", response_model=Page[ShortlistItem])
def get_shortlist(
    min_fit: int | None = Query(None, alias="minFit"),
    sort: str = Query("fit", alias="sortBy"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, alias="pageSize", ge=1, le=200),
    session: Session = Depends(get_session),
):
    result = board.list_shortlist(
        session, min_fit=min_fit, sort=sort, page=page, page_size=page_size
    )
    return to_page(result, ShortlistItem)


@router.get("/pipeline", response_model=Page[PipelineItem])
def get_pipeline(
    status: str | None = None,
    min_fit: int | None = Query(None, alias="minFit"),
    q: str | None = None,
    sort: str = Query("stage", alias="sortBy"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, alias="pageSize", ge=1, le=200),
    session: Session = Depends(get_session),
):
    result = board.list_pipeline(
        session, status=status, min_fit=min_fit, q=q, sort=sort, page=page, page_size=page_size
    )
    return to_page(result, PipelineItem)


@router.get("/triage", response_model=Page[TriageItem])
def get_triage(
    archived: bool = False,
    status: str | None = None,
    min_fit: int | None = Query(None, alias="minFit"),
    sort: str = Query("fit", alias="sortBy"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, alias="pageSize", ge=1, le=200),
    session: Session = Depends(get_session),
):
    result = board.list_triage(
        session, archived=archived, status=status, min_fit=min_fit,
        sort=sort, page=page, page_size=page_size
    )
    return to_page(result, TriageItem)
