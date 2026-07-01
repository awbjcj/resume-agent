import httpx

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
    resp = httpx.get(f"{_BASE}/{token}/jobs", params={"content": "true"}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def parse_greenhouse(payload: dict, company: str) -> list[RawJob]:
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
            )
        )
    return jobs


class GreenhouseConnector:
    """Pulls every open role from each configured Greenhouse board, then filters.

    Boards are isolated: one bad token (a 404, a timeout) is recorded in
    ``failures`` and skipped, so the remaining boards still contribute jobs.
    """

    name = "greenhouse"

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
                self._get_board(board.token), board.display()
            ),
            search=search,
            limit=limit,
            key=lambda board: board.token,
            on_error=http_failure,
        )

    def _get_board(self, token: str) -> dict:
        return fetch_greenhouse_board(token)
