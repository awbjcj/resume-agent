import httpx

from resume_agent.discovery.connectors.base import RawJob, SkipSeen
from resume_agent.discovery.connectors.dates import parse_iso_datetime
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.harvest import harvest_detailed
from resume_agent.discovery.connectors.text import html_to_markdown, jobposting_json_ld
from resume_agent.discovery.search_config import SearchConfig


def board_url(token: str) -> str:
    return f"https://{token}.breezy.hr/json"


def parse_breezy(payload: list, token: str) -> list[RawJob]:
    return [
        RawJob(
            source="breezy",
            url=item.get("url"),
            company=(item.get("company") or {}).get("name") or token,
            title=item.get("name"),
            location=(item.get("location") or {}).get("name"),
            jd_text="",
            posted_at=parse_iso_datetime(item.get("published_date")),
        )
        for item in payload
    ]


def apply_detail(row: RawJob, detail: dict) -> None:
    posting = jobposting_json_ld(detail["html"])
    if posting is None:
        raise ValueError("Breezy detail did not contain JobPosting JSON-LD")
    row.url = str(posting.get("url") or row.url).split("?", 1)[0]
    row.title = posting.get("title") or row.title
    row.jd_text = html_to_markdown(posting.get("description") or "")
    organization = posting.get("hiringOrganization") or {}
    row.company = organization.get("name") or row.company


def fetch_breezy(
    target: AtsTarget,
    search: SearchConfig,
    limit: int | None = None,
    skip_seen: SkipSeen | None = None,
) -> list[RawJob]:
    response = httpx.get(board_url(target.token), timeout=30)
    response.raise_for_status()
    rows = parse_breezy(response.json(), target.token)

    def fetch_detail(row: RawJob) -> dict | None:
        if not row.url:
            return None
        detail = httpx.get(row.url, timeout=30)
        detail.raise_for_status()
        return {"html": detail.text}

    return harvest_detailed(
        rows,
        fetch_detail,
        apply_detail,
        search=search,
        limit=limit,
        skip_seen=skip_seen,
    )
