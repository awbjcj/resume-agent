from dataclasses import dataclass

import httpx

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.dates import parse_iso_datetime
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.text import html_to_text, relevance_gate
from resume_agent.discovery.search_config import SearchConfig

_PAGE = 20  # cxs page size
_MAX_OFFSET = 1000  # safety ceiling: <=50 pages even if a tenant ignores searchText


@dataclass
class WorkdayRow(RawJob):
    """A list-page RawJob that remembers its detail path for the N+1 fetch."""

    external_path: str = ""


def _base(target: AtsTarget) -> str:
    return f"https://{target.tenant}.{target.datacenter}.myworkdayjobs.com"


def cxs_jobs_url(target: AtsTarget) -> str:
    return f"{_base(target)}/wday/cxs/{target.tenant}/{target.site}/jobs"


def _search_text(search: SearchConfig) -> str:
    terms = [t.strip() for t in (*search.titles, *search.keywords) if t.strip()]
    return terms[0] if terms else ""


def list_request_body(search: SearchConfig, offset: int) -> dict:
    return {"appliedFacets": {}, "limit": _PAGE, "offset": offset, "searchText": _search_text(search)}


def parse_list_rows(target: AtsTarget, page: dict) -> list[WorkdayRow]:
    rows: list[WorkdayRow] = []
    for item in page.get("jobPostings", []):
        path = item.get("externalPath") or ""
        rows.append(
            WorkdayRow(
                source="workday",
                url=f"{_base(target)}{path}" if path else None,
                company=target.tenant,
                title=item.get("title"),
                location=item.get("locationsText"),
                jd_text="",
                external_path=path,
            )
        )
    return rows


def cxs_detail_url(target: AtsTarget, external_path: str) -> str:
    # external_path begins with "/job/..."; the detail endpoint is "<site>/job/...".
    suffix = external_path[len("/job") :] if external_path.startswith("/job") else external_path
    return f"{_base(target)}/wday/cxs/{target.tenant}/{target.site}/job{suffix}"


def apply_detail(row: WorkdayRow, detail: dict) -> None:
    info = detail.get("jobPostingInfo") or {}
    row.jd_text = html_to_text(info.get("jobDescription", ""))
    if info.get("externalUrl"):
        row.url = info["externalUrl"]
    if info.get("location"):
        row.location = info["location"]
    row.posted_at = parse_iso_datetime(info.get("startDate"))


def _list_pages(target: AtsTarget, search: SearchConfig):
    offset = 0
    while offset <= _MAX_OFFSET:
        body = list_request_body(search, offset)
        resp = httpx.post(cxs_jobs_url(target), json=body, timeout=30)
        resp.raise_for_status()
        page = resp.json()
        postings = page.get("jobPostings") or []
        if not postings:
            return
        yield from parse_list_rows(target, page)
        total = page.get("total")
        offset += _PAGE
        if isinstance(total, int) and offset >= total:
            return


def fetch_workday(target: AtsTarget, search: SearchConfig, limit: int | None = None) -> list[RawJob]:
    """List (request-shaped) -> gate on title/location -> detail-fetch survivors only."""
    survivors: list[WorkdayRow] = []
    for row in _list_pages(target, search):
        if relevance_gate([row], search):  # (C) gate BEFORE spending a detail call
            survivors.append(row)
            if limit is not None and len(survivors) >= limit:
                break

    jobs: list[RawJob] = []
    for row in survivors:
        resp = httpx.post(cxs_detail_url(target, row.external_path), json={}, timeout=30)
        resp.raise_for_status()
        apply_detail(row, resp.json())
        jobs.append(row)
    return jobs
