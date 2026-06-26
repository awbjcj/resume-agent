"""Read-only board lists: shortlist, pipeline, triage. Paginated + core filters."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from resume_agent.api.deps import get_session
from resume_agent.api.mappers import to_board_page
from resume_agent.api.schemas.base import BoardPage
from resume_agent.api.schemas.jobs import PipelineItem, ShortlistItem, TriageItem
from resume_agent.services import board

router = APIRouter()


def _csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(part.strip() for part in value.split(",") if part.strip())


def _filter_from_query(
    *,
    q: str | None = None,
    source: str | None = None,
    status: str | None = None,
    remote: str | None = None,
    sponsorship: str | None = None,
    seniority: str | None = None,
    employment_type: str | None = None,
    industry: str | None = None,
    country: str | None = None,
    region: str | None = None,
    city: str | None = None,
    company_size: str | None = None,
    skills: str | None = None,
    min_fit: int | None = None,
    max_fit: int | None = None,
    min_salary: int | None = None,
    stale_days: int | None = None,
    sort: str = "fit",
    archived: bool = False,
) -> board.BoardFilter:
    return board.BoardFilter(
        q=q,
        source=_csv(source),
        status=_csv(status),
        remote=_csv(remote),
        sponsorship=_csv(sponsorship),
        seniority=_csv(seniority),
        employment_type=_csv(employment_type),
        industry=_csv(industry),
        country=_csv(country),
        region=_csv(region),
        city=_csv(city),
        company_size=_csv(company_size),
        skills=_csv(skills),
        min_fit=min_fit,
        max_fit=max_fit,
        min_salary=min_salary,
        stale_days=stale_days,
        sort=sort,
        archived=archived,
    )


@router.get("/shortlist", response_model=BoardPage[ShortlistItem])
def get_shortlist(
    q: str | None = None,
    source: str | None = None,
    status: str | None = None,
    remote: str | None = None,
    sponsorship: str | None = None,
    seniority: str | None = None,
    employment_type: str | None = Query(None, alias="employmentType"),
    industry: str | None = None,
    country: str | None = None,
    region: str | None = None,
    city: str | None = None,
    company_size: str | None = Query(None, alias="companySize"),
    skills: str | None = None,
    min_fit: int | None = Query(None, alias="minFit"),
    max_fit: int | None = Query(None, alias="maxFit"),
    min_salary: int | None = Query(None, alias="minSalary"),
    stale_days: int | None = Query(None, alias="staleDays"),
    sort: str = Query("fit", alias="sortBy"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, alias="pageSize", ge=1, le=200),
    session: Session = Depends(get_session),
):
    board_filter = _filter_from_query(
        q=q, source=source, status=status, remote=remote, sponsorship=sponsorship,
        seniority=seniority, employment_type=employment_type, industry=industry,
        country=country, region=region, city=city, company_size=company_size,
        skills=skills, min_fit=min_fit, max_fit=max_fit, min_salary=min_salary,
        stale_days=stale_days, sort=sort,
    )
    result = board.list_board(
        session, "shortlist", board_filter=board_filter, page=page, page_size=page_size,
    )
    return to_board_page(result.page, ShortlistItem, result.facets)


@router.get("/pipeline", response_model=BoardPage[PipelineItem])
def get_pipeline(
    source: str | None = None,
    status: str | None = None,
    remote: str | None = None,
    sponsorship: str | None = None,
    seniority: str | None = None,
    employment_type: str | None = Query(None, alias="employmentType"),
    industry: str | None = None,
    country: str | None = None,
    region: str | None = None,
    city: str | None = None,
    company_size: str | None = Query(None, alias="companySize"),
    skills: str | None = None,
    min_fit: int | None = Query(None, alias="minFit"),
    max_fit: int | None = Query(None, alias="maxFit"),
    min_salary: int | None = Query(None, alias="minSalary"),
    stale_days: int | None = Query(None, alias="staleDays"),
    q: str | None = None,
    sort: str = Query("stage", alias="sortBy"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, alias="pageSize", ge=1, le=200),
    session: Session = Depends(get_session),
):
    board_filter = _filter_from_query(
        q=q, source=source, status=status, remote=remote, sponsorship=sponsorship,
        seniority=seniority, employment_type=employment_type, industry=industry,
        country=country, region=region, city=city, company_size=company_size,
        skills=skills, min_fit=min_fit, max_fit=max_fit, min_salary=min_salary,
        stale_days=stale_days, sort=sort,
    )
    result = board.list_board(
        session, "pipeline", board_filter=board_filter, page=page, page_size=page_size,
    )
    return to_board_page(result.page, PipelineItem, result.facets)


@router.get("/triage", response_model=BoardPage[TriageItem])
def get_triage(
    archived: bool = False,
    q: str | None = None,
    source: str | None = None,
    status: str | None = None,
    remote: str | None = None,
    sponsorship: str | None = None,
    seniority: str | None = None,
    employment_type: str | None = Query(None, alias="employmentType"),
    industry: str | None = None,
    country: str | None = None,
    region: str | None = None,
    city: str | None = None,
    company_size: str | None = Query(None, alias="companySize"),
    skills: str | None = None,
    min_fit: int | None = Query(None, alias="minFit"),
    max_fit: int | None = Query(None, alias="maxFit"),
    min_salary: int | None = Query(None, alias="minSalary"),
    stale_days: int | None = Query(None, alias="staleDays"),
    sort: str = Query("fit", alias="sortBy"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, alias="pageSize", ge=1, le=200),
    session: Session = Depends(get_session),
):
    board_filter = _filter_from_query(
        q=q, source=source, status=status, remote=remote, sponsorship=sponsorship,
        seniority=seniority, employment_type=employment_type, industry=industry,
        country=country, region=region, city=city, company_size=company_size,
        skills=skills, min_fit=min_fit, max_fit=max_fit, min_salary=min_salary,
        stale_days=stale_days, sort=sort, archived=archived,
    )
    result = board.list_board(
        session, "triage", board_filter=board_filter, page=page, page_size=page_size,
    )
    return to_board_page(result.page, TriageItem, result.facets)
