from dataclasses import dataclass

import httpx

from resume_agent.discovery.connectors.base import RawJob, SkipSeen
from resume_agent.discovery.connectors.dates import parse_iso_datetime
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.harvest import harvest_detailed
from resume_agent.discovery.connectors.text import html_to_markdown
from resume_agent.discovery.search_config import SearchConfig


@dataclass
class BambooHrRow(RawJob):
    opening_id: str = ""


def list_url(token: str) -> str:
    return f"https://{token}.bamboohr.com/careers/list"


def detail_url(token: str, opening_id: str) -> str:
    return f"https://{token}.bamboohr.com/careers/{opening_id}/detail"


def _location(item: dict) -> str | None:
    location = item.get("atsLocation") or item.get("location") or {}
    parts = (
        location.get("city"),
        location.get("state") or location.get("province"),
        location.get("country"),
    )
    result = ", ".join(filter(None, parts))
    return result or ("Remote" if item.get("isRemote") else None)


def parse_bamboohr(payload: dict, token: str) -> list[BambooHrRow]:
    rows = []
    for item in payload.get("result") or []:
        opening_id = str(item.get("id") or "")
        rows.append(
            BambooHrRow(
                source="bamboohr",
                url=f"https://{token}.bamboohr.com/careers/{opening_id}"
                if opening_id
                else None,
                company=token,
                title=item.get("jobOpeningName"),
                location=_location(item),
                jd_text="",
                opening_id=opening_id,
            )
        )
    return rows


def apply_detail(row: BambooHrRow, detail: dict) -> None:
    opening = ((detail.get("result") or {}).get("jobOpening")) or {}
    row.url = opening.get("jobOpeningShareUrl") or row.url
    row.title = opening.get("jobOpeningName") or row.title
    row.jd_text = html_to_markdown(opening.get("description") or "")
    row.posted_at = parse_iso_datetime(opening.get("datePosted"))
    row.location = _location(opening) or row.location


def fetch_bamboohr(
    target: AtsTarget,
    search: SearchConfig,
    limit: int | None = None,
    skip_seen: SkipSeen | None = None,
) -> list[RawJob]:
    response = httpx.get(list_url(target.token), timeout=30)
    response.raise_for_status()
    rows = parse_bamboohr(response.json(), target.token)

    def fetch_detail(row: BambooHrRow) -> dict | None:
        if not row.opening_id:
            return None
        detail = httpx.get(detail_url(target.token, row.opening_id), timeout=30)
        detail.raise_for_status()
        return detail.json()

    return harvest_detailed(
        rows,
        fetch_detail,
        apply_detail,
        search=search,
        limit=limit,
        skip_seen=skip_seen,
    )
