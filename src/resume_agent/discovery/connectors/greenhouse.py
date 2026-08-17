from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from typing import Literal
from urllib.parse import urlsplit

import httpx

from resume_agent.discovery.connectors import http as board

from resume_agent.discovery.connectors.base import (
    FetchResult,
    RawJob,
    SkipSeen,
    http_failure,
)
from resume_agent.discovery.connectors.config import GreenhouseBoard
from resume_agent.discovery.connectors.dates import parse_iso_datetime
from resume_agent.discovery.connectors.harvest import harvest
from resume_agent.discovery.connectors.text import html_to_markdown, join_locations
from resume_agent.discovery.search_config import SearchConfig
from resume_agent.discovery.url_ingest import fetch as url_fetch

_BASE = "https://boards-api.greenhouse.io/v1/boards"

# Greenhouse serves this literal string for a job whose location is unset, so it
# reaches us as a value rather than as an absent key. Observed live on Stripe's
# board (22 of 578 jobs).
_PLACEHOLDER_LOCATIONS = {"n/a", "none", "-", "tbd"}

# Boards define their own `metadata` custom fields, so the names are per-board
# rather than an API enum. Only names that are known to carry a sidebar fact are
# rendered -- a blanket passthrough would dump a board's internal bookkeeping
# fields (req owner, budget code) into the JD.
_METADATA_LABELS = {
    "location type": "Workplace Type",
    "workplace type": "Workplace Type",
    "remote status": "Workplace Type",
    "employment type": "Employment Type",
    "job type": "Employment Type",
}

_GREENHOUSE_HOSTS = {"boards.greenhouse.io", "job-boards.greenhouse.io"}


def _normalize_location(value) -> str | None:
    """Remove repeated entries from Greenhouse's composite location label."""
    if not isinstance(value, str):
        return None
    location = value.strip()
    if not location or location.lower() in _PLACEHOLDER_LOCATIONS:
        return None
    return join_locations([location])


def _names(items) -> str | None:
    """Join the `name` of a Greenhouse `departments`/`offices` list."""
    if not isinstance(items, list):
        return None
    names = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return ", ".join(dict.fromkeys(names)) or None


def _metadata_lines(items) -> list[str]:
    lines = []
    if not isinstance(items, list):
        return lines
    for item in items:
        if not isinstance(item, dict):
            continue
        label = _METADATA_LABELS.get(str(item.get("name") or "").strip().lower())
        value = item.get("value")
        # `value` is null on an unanswered custom field, and a list on a
        # multi-select one.
        if isinstance(value, list):
            value = ", ".join(str(part) for part in value if part)
        if label and isinstance(value, str) and value.strip():
            lines.append(f"{label}: {value.strip()}")
    return lines


def _sidebar_lines(item: dict) -> list[str]:
    """The facts a Greenhouse posting shows beside its body, as text lines.

    Location, department, and the board's workplace-type custom field live in
    dedicated API fields rather than in ``content``, so they are rendered as
    ``Label: value`` lines prepended to jd_text -- the same shape
    ``ashby.parse_ashby`` uses -- for the relevance gate, criteria extraction,
    and tailoring to read.
    """
    lines: list[str] = []

    location = _normalize_location((item.get("location") or {}).get("name"))
    if location:
        lines.append(f"Location: {location}")

    lines.extend(_metadata_lines(item.get("metadata")))

    if department := _names(item.get("departments")):
        lines.append(f"Department: {department}")

    return lines


def fetch_greenhouse_board(token: str) -> dict:
    """GET a Greenhouse board's jobs payload with content."""
    resp = board.get(f"{_BASE}/{token}/jobs", params={"content": "true"})
    resp.raise_for_status()
    return resp.json()


def fetch_greenhouse_job(token: str, job_id: str) -> dict:
    """GET one Greenhouse posting by id -- same item shape as a board's ``jobs`` entry.

    Lets a pasted posting URL reuse the board API's content rather than scraping
    the rendered page, whose markup differs between the legacy ``boards.`` and
    modern ``job-boards.`` layouts.
    """
    resp = board.get(f"{_BASE}/{token}/jobs/{job_id}", params={"content": "true"})
    resp.raise_for_status()
    return resp.json()


def fetch_greenhouse_board_name(token: str) -> str | None:
    """Resolve the organization name from Greenhouse's public board endpoint."""
    response = board.get(f"{_BASE}/{token}")
    response.raise_for_status()
    name = response.json().get("name")
    return name.strip() if isinstance(name, str) and name.strip() else None


def parse_greenhouse(
    payload: dict,
    company: str,
    stale_company: str | None = None,
    company_provenance: Literal["configured", "provider", "token"] = "configured",
) -> list[RawJob]:
    """Map a Greenhouse board `jobs` payload to RawJobs."""
    jobs: list[RawJob] = []
    for item in payload.get("jobs", []):
        location = _normalize_location((item.get("location") or {}).get("name"))
        jd_text = html_to_markdown(item.get("content", ""))
        if sidebar := _sidebar_lines(item):
            jd_text = "\n".join(sidebar) + ("\n\n" + jd_text if jd_text else "")
        jobs.append(
            RawJob(
                source="greenhouse",
                url=item.get("absolute_url"),
                company=company,
                title=item.get("title"),
                location=location,
                jd_text=jd_text,
                posted_at=parse_iso_datetime(item.get("updated_at")),
                stale_company=stale_company,
                company_provenance=company_provenance,
            )
        )
    return jobs


def _employer_hosted(url: str | None) -> bool:
    return bool(url and (urlsplit(url).hostname or "").lower() not in _GREENHOUSE_HOSTS)


def _enrich_employer_hosted(row: RawJob) -> RawJob:
    if not _employer_hosted(row.url):
        return row
    try:
        page = url_fetch.fetch_static(row.url or "")
        # Import at call time: ats_readers reuses parse_greenhouse, so importing
        # it while this connector module initializes would create a cycle.
        from resume_agent.discovery.url_ingest.ats_readers import (
            read_employer_hosted_greenhouse,
            with_json_ld_meta,
        )

        extracted = with_json_ld_meta(
            read_employer_hosted_greenhouse(page.html), page.html
        )
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return row
    if extracted is None:
        return row
    if extracted.jd_text:
        row.jd_text = extracted.jd_text
    if extracted.location:
        row.location = extracted.location
    return row


def _enrich_employer_hosted_rows(rows: list[RawJob]) -> list[RawJob]:
    if len(rows) < 2:
        return [_enrich_employer_hosted(row) for row in rows]
    from resume_agent.config import get_settings

    workers = min(len(rows), max(1, get_settings().detail_fetch_concurrency))
    tasks = [(copy_context(), row) for row in rows]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(
            pool.map(lambda task: task[0].run(_enrich_employer_hosted, task[1]), tasks)
        )


class GreenhouseConnector:
    """Pulls every open role from each configured Greenhouse board, then filters.

    Boards are isolated: one bad token (a 404, a timeout) is recorded in
    ``failures`` and skipped, so the remaining boards still contribute jobs.
    """

    name = "greenhouse"
    concurrent_fetch = True

    def __init__(self, boards: list[GreenhouseBoard]):
        self.boards = boards

    def fetch(
        self,
        search: SearchConfig,
        limit: int | None = None,
        skip_seen: SkipSeen | None = None,
    ) -> FetchResult:
        return harvest(
            self.boards,
            lambda board: parse_greenhouse(
                self._get_board(board.token), *self._company_pair(board)
            ),
            search=search,
            limit=limit,
            key=lambda board: board.token,
            on_error=http_failure,
            skip_seen=skip_seen,
            unit_limit=lambda board: board.limit,
            transform_kept=lambda board, rows: _enrich_employer_hosted_rows(rows),
        )

    def _get_board(self, token: str) -> dict:
        return fetch_greenhouse_board(token)

    def _get_board_name(self, token: str) -> str | None:
        return fetch_greenhouse_board_name(token)

    def _company_pair(
        self, board: GreenhouseBoard
    ) -> tuple[str, str | None, Literal["configured", "provider", "token"]]:
        if board.company:
            return (
                board.company,
                board.token if board.company != board.token else None,
                "configured",
            )
        try:
            resolved = self._get_board_name(board.token)
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            resolved = None
        company = resolved or board.token
        return (
            company,
            board.token if company != board.token else None,
            "provider" if resolved else "token",
        )
