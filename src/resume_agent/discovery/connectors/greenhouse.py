from typing import Literal

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
from resume_agent.discovery.connectors.text import html_to_markdown
from resume_agent.discovery.search_config import SearchConfig

_BASE = "https://boards-api.greenhouse.io/v1/boards"


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
        location = (item.get("location") or {}).get("name")
        jobs.append(
            RawJob(
                source="greenhouse",
                url=item.get("absolute_url"),
                company=company,
                title=item.get("title"),
                location=location,
                jd_text=html_to_markdown(item.get("content", "")),
                posted_at=parse_iso_datetime(item.get("updated_at")),
                stale_company=stale_company,
                company_provenance=company_provenance,
            )
        )
    return jobs


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
