from urllib.parse import urljoin


from resume_tailor_harness.discovery.connectors import http as board
from bs4 import BeautifulSoup

from resume_tailor_harness.discovery.connectors.base import RawJob, SkipSeen
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
    return f"https://{token}.applytojob.com/apply/jobs"


def parse_listing(html: str, token: str) -> list[RawJob]:
    base = board_url(token)
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    seen_urls = set()
    for link in soup.select("a.job_title_link[href]"):
        href = link.get("href") or ""
        url = urljoin(base, str(href))
        if url in seen_urls:
            continue
        seen_urls.add(url)
        row = link.find_parent("tr")
        cells = row.find_all("td") if row else []
        location = cells[-1].get_text(" ", strip=True) if len(cells) > 1 else None
        rows.append(
            RawJob(
                source="jazzhr",
                url=url,
                company=token,
                title=link.get_text(" ", strip=True),
                location=location,
                jd_text="",
                company_provenance="token",
            )
        )
    return rows


def apply_detail(row: RawJob, detail: dict) -> None:
    posting = jobposting_json_ld(detail["html"])
    if posting is None:
        raise ValueError("JazzHR detail did not contain JobPosting JSON-LD")
    row.url = posting.get("url") or row.url
    row.title = posting.get("title") or row.title
    # The markup carries the pay band, employment type and remote status
    # alongside the body; `description` alone drops all three.
    row.jd_text = with_meta_lines(
        jobposting_meta_lines(posting),
        html_to_markdown(posting.get("description") or ""),
    )
    row.posted_at = parse_iso_datetime(posting.get("datePosted"))
    organization = posting.get("hiringOrganization") or {}
    row.company = organization.get("name") or row.company
    if organization.get("name"):
        row.company_provenance = "provider"
    if location := jobposting_location(posting):
        row.location = location


def fetch_jazzhr(
    target: AtsTarget,
    search: SearchConfig,
    limit: int | None = None,
    skip_seen: SkipSeen | None = None,
) -> list[RawJob]:
    response = board.get(board_url(target.token))
    response.raise_for_status()
    rows = parse_listing(response.text, target.token)

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
