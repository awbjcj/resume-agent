from resume_tailor_harness.discovery.connectors import http as board

from resume_tailor_harness.discovery.connectors.base import RawJob, SkipSeen, provenance_for
from resume_tailor_harness.discovery.connectors.dates import parse_iso_datetime
from resume_tailor_harness.discovery.connectors.detect import AtsTarget
from resume_tailor_harness.discovery.connectors.harvest import harvest_detailed
from resume_tailor_harness.discovery.connectors.text import (
    html_to_markdown,
    jobposting_json_ld,
    jobposting_location,
    jobposting_meta_lines,
    with_meta_lines,
)
from resume_tailor_harness.discovery.search_config import SearchConfig


def board_url(token: str) -> str:
    return f"https://{token}.breezy.hr/json"


def parse_breezy(payload: list, token: str) -> list[RawJob]:
    rows = []
    for item in payload:
        provider_company = (item.get("company") or {}).get("name")
        rows.append(
            RawJob(
                source="breezy",
                url=item.get("url"),
                company=provider_company or token,
                title=item.get("name"),
                location=(item.get("location") or {}).get("name"),
                jd_text="",
                posted_at=parse_iso_datetime(item.get("published_date")),
                company_provenance=provenance_for(provider_company),
            )
        )
    return rows


def apply_detail(row: RawJob, detail: dict) -> None:
    posting = jobposting_json_ld(detail["html"])
    if posting is None:
        raise ValueError("Breezy detail did not contain JobPosting JSON-LD")
    row.url = str(posting.get("url") or row.url).split("?", 1)[0]
    row.title = posting.get("title") or row.title
    # The markup carries the pay band, employment type and remote status
    # alongside the body; `description` alone drops all three.
    row.jd_text = with_meta_lines(
        jobposting_meta_lines(posting),
        html_to_markdown(posting.get("description") or ""),
    )
    if location := jobposting_location(posting):
        row.location = location
    organization = posting.get("hiringOrganization") or {}
    row.company = organization.get("name") or row.company
    if organization.get("name"):
        row.company_provenance = "provider"


def fetch_breezy(
    target: AtsTarget,
    search: SearchConfig,
    limit: int | None = None,
    skip_seen: SkipSeen | None = None,
) -> list[RawJob]:
    response = board.get(board_url(target.token))
    response.raise_for_status()
    rows = parse_breezy(response.json(), target.token)

    def fetch_detail(row: RawJob) -> dict | None:
        if not row.url:
            return None
        detail = board.get(row.url)
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
