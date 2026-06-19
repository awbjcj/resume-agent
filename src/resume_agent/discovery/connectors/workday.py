from dataclasses import dataclass

import httpx

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.dates import parse_iso_datetime
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.text import (
    html_to_text,
    primary_search_term,
    relevance_gate,
    title_relevance_gate,
)
from resume_agent.discovery.search_config import SearchConfig

_PAGE = 20  # cxs page size
_MAX_OFFSET = 1000  # safety ceiling: <=51 pages (~1020 rows) even if a tenant ignores searchText


@dataclass
class WorkdayRow(RawJob):
    """A list-page RawJob that remembers its detail path for the N+1 fetch."""

    external_path: str = ""


def _base(target: AtsTarget) -> str:
    return f"https://{target.tenant}.{target.datacenter}.myworkdayjobs.com"


def cxs_jobs_url(target: AtsTarget) -> str:
    return f"{_base(target)}/wday/cxs/{target.tenant}/{target.site}/jobs"


def list_request_body(search: SearchConfig, offset: int) -> dict:
    return {
        "appliedFacets": {},
        "limit": _PAGE,
        "offset": offset,
        "searchText": primary_search_term(search),
    }


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
    # external_path already begins with "/job/..."; the cxs detail endpoint is the
    # site path with that suffix appended verbatim (no special-casing of the prefix).
    return f"{_base(target)}/wday/cxs/{target.tenant}/{target.site}{external_path}"


def apply_detail(row: WorkdayRow, detail: dict) -> None:
    info = detail.get("jobPostingInfo") or {}
    row.jd_text = html_to_text(info.get("jobDescription", ""))
    if info.get("externalUrl"):
        row.url = info["externalUrl"]
    if info.get("location"):
        row.location = info["location"]
    if info.get("companyName"):
        row.company = info["companyName"]
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
    jobs: list[RawJob] = []
    for row in _list_pages(target, search):
        # Gate only on title-safe constraints before the N+1 detail fetch. Keyword/title fallback
        # needs jd_text, so the full relevance gate runs after detail is applied.
        if not title_relevance_gate([row], search):
            continue
        if not row.external_path:
            continue  # no detail path -> cannot fetch a description; skip rather than POST a bad URL
        try:
            resp = httpx.get(cxs_detail_url(target, row.external_path), timeout=30)
            resp.raise_for_status()
        except httpx.HTTPError:
            continue  # one stale/failed detail endpoint must not discard the whole batch
        apply_detail(row, resp.json())
        if relevance_gate([row], search):
            jobs.append(row)
            if limit is not None and len(jobs) >= limit:
                break
    return jobs
