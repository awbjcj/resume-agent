from dataclasses import dataclass

import httpx

from resume_agent.discovery.connectors.base import RawJob, SkipSeen
from resume_agent.discovery.connectors.dates import parse_iso_datetime
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.harvest import harvest_detailed
from resume_agent.discovery.connectors.text import html_to_markdown, primary_search_term
from resume_agent.discovery.search_config import SearchConfig

_BASE = "https://api.smartrecruiters.com/v1/companies"
_PAGE_SIZE = 100
_MAX_OFFSET = 1000


@dataclass
class SmartRecruitersRow(RawJob):
    posting_id: str = ""


def postings_url(company: str) -> str:
    return f"{_BASE}/{company}/postings"


def detail_url(company: str, posting_id: str) -> str:
    return f"{postings_url(company)}/{posting_id}"


def list_params(search: SearchConfig, offset: int) -> dict[str, str | int]:
    params: dict[str, str | int] = {"limit": _PAGE_SIZE, "offset": offset}
    if term := primary_search_term(search):
        params["q"] = term
    return params


def _location(location: dict | None) -> str | None:
    if not location:
        return None
    return (
        ", ".join(
            filter(
                None,
                (location.get("city"), location.get("region"), location.get("country")),
            )
        )
        or None
    )


def parse_postings(payload: dict, company: str) -> list[SmartRecruitersRow]:
    rows = []
    for item in payload.get("content") or []:
        posting_id = str(item.get("id") or "")
        rows.append(
            SmartRecruitersRow(
                source="smartrecruiters",
                url=(
                    f"https://jobs.smartrecruiters.com/{company}/{posting_id}"
                    if posting_id
                    else None
                ),
                company=(item.get("company") or {}).get("name") or company,
                title=item.get("name"),
                location=_location(item.get("location")),
                jd_text="",
                posted_at=parse_iso_datetime(item.get("releasedDate")),
                posting_id=posting_id,
            )
        )
    return rows


def apply_detail(row: SmartRecruitersRow, detail: dict) -> None:
    sections = ((detail.get("jobAd") or {}).get("sections")) or {}
    names = (
        "companyDescription",
        "jobDescription",
        "qualifications",
        "additionalInformation",
    )
    row.jd_text = html_to_markdown(
        "\n".join((sections.get(name) or {}).get("text") or "" for name in names)
    )
    row.url = detail.get("applyUrl") or detail.get("postingUrl") or row.url


def _list_pages(target: AtsTarget, search: SearchConfig):
    for offset in range(0, _MAX_OFFSET + 1, _PAGE_SIZE):
        response = httpx.get(
            postings_url(target.token), params=list_params(search, offset), timeout=30
        )
        response.raise_for_status()
        payload = response.json()
        rows = parse_postings(payload, target.token)
        yield from rows
        total = payload.get("totalFound")
        if not rows or isinstance(total, int) and offset + _PAGE_SIZE >= total:
            break


def _fetch_detail(target: AtsTarget, row: SmartRecruitersRow) -> dict | None:
    if not row.posting_id:
        return None
    response = httpx.get(detail_url(target.token, row.posting_id), timeout=30)
    response.raise_for_status()
    return response.json()


def fetch_smartrecruiters(
    target: AtsTarget,
    search: SearchConfig,
    limit: int | None = None,
    skip_seen: SkipSeen | None = None,
) -> list[RawJob]:
    return harvest_detailed(
        _list_pages(target, search),
        lambda row: _fetch_detail(target, row),
        apply_detail,
        search=search,
        limit=limit,
        skip_seen=skip_seen,
    )
