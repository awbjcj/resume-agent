
from resume_agent.discovery.connectors import http as board

from resume_agent.discovery.connectors.base import (
    FetchResult,
    RawJob,
    SkipSeen,
    http_failure,
)
from resume_agent.discovery.connectors.config import AshbyBoard
from resume_agent.discovery.connectors.dates import parse_iso_datetime
from resume_agent.discovery.connectors.harvest import harvest
from resume_agent.discovery.connectors.text import html_to_markdown, join_locations
from resume_agent.discovery.search_config import SearchConfig

_BASE = "https://api.ashbyhq.com/posting-api/job-board"

# Ashby's posting-api employmentType enum -> a readable label for the JD sidebar.
_EMPLOYMENT_TYPE_LABELS = {
    "FullTime": "Full time",
    "PartTime": "Part time",
    "Intern": "Internship",
    "Temporary": "Temporary",
    "Contract": "Contract",
    "Apprenticeship": "Apprenticeship",
}


def _location(item: dict) -> str | None:
    secondary = [
        entry.get("location")
        for entry in item.get("secondaryLocations") or []
        if isinstance(entry, dict)
    ]
    return join_locations([item.get("location"), *secondary])


def _sidebar_lines(item: dict) -> list[str]:
    """The left-sidebar facts (location, employment type, department, pay) an
    Ashby job page shows, rendered as text lines so they ride along in jd_text
    for the relevance gate, criteria extraction, and tailoring to read.
    """
    lines: list[str] = []

    location = item.get("location")
    secondary = [
        loc.get("location") for loc in item.get("secondaryLocations") or [] if loc.get("location")
    ]
    if location and secondary:
        lines.append(f"Location: {location} (also: {', '.join(secondary)})")
    elif location:
        lines.append(f"Location: {location}")

    workplace_type = item.get("workplaceType")
    if workplace_type:
        lines.append(f"Workplace Type: {workplace_type}")

    employment_type = item.get("employmentType")
    if employment_type:
        lines.append(f"Employment Type: {_EMPLOYMENT_TYPE_LABELS.get(employment_type, employment_type)}")

    department = item.get("department")
    team = item.get("team")
    if department and team and department != team:
        lines.append(f"Department: {department} ({team})")
    elif department or team:
        lines.append(f"Department: {department or team}")

    compensation = item.get("compensation") or {}
    summary = compensation.get("compensationTierSummary") or compensation.get(
        "scrapeableCompensationSalarySummary"
    )
    if summary:
        lines.append(f"Compensation: {summary}")

    return lines


def parse_ashby(payload: dict, company: str) -> list[RawJob]:
    """Map an Ashby posting-api jobs payload to RawJobs.

    Location, employment type, department, and compensation live in dedicated
    fields on the job page's sidebar rather than the JD body, so they are
    rendered as a text block prepended to jd_text.
    """
    jobs: list[RawJob] = []
    for item in payload.get("jobs", []):
        jd_text = item.get("descriptionPlain") or html_to_markdown(
            item.get("descriptionHtml", "")
        )
        sidebar = _sidebar_lines(item)
        if sidebar:
            jd_text = "\n".join(sidebar) + "\n\n" + jd_text
        jobs.append(
            RawJob(
                source="ashby",
                url=item.get("jobUrl"),
                company=company,
                title=item.get("title"),
                location=_location(item),
                jd_text=jd_text,
                posted_at=parse_iso_datetime(item.get("publishedAt")),
            )
        )
    return jobs


def fetch_ashby_board(token: str) -> dict:
    """GET an Ashby job board's postings payload, including compensation tiers."""
    resp = board.get(f"{_BASE}/{token}?includeCompensation=true")
    resp.raise_for_status()
    return resp.json()


class AshbyConnector:
    name = "ashby"
    concurrent_fetch = True

    def __init__(self, boards: list[AshbyBoard]):
        self.boards = boards

    def fetch(
        self,
        search: SearchConfig,
        limit: int | None = None,
        skip_seen: SkipSeen | None = None,
    ) -> FetchResult:
        return harvest(
            self.boards,
            lambda board: parse_ashby(fetch_ashby_board(board.token), board.display()),
            search=search,
            limit=limit,
            key=lambda board: board.token,
            on_error=http_failure,
            skip_seen=skip_seen,
            unit_limit=lambda board: board.limit,
        )
