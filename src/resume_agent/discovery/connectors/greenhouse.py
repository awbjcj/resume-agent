import httpx

from resume_agent.discovery.connectors.base import RawJob, board_error
from resume_agent.discovery.connectors.config import GreenhouseBoard
from resume_agent.discovery.connectors.dates import parse_iso_datetime
from resume_agent.discovery.connectors.text import html_to_text, relevance_gate
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
                jd_text=html_to_text(item.get("content", "")),
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
        # token -> reason for boards that failed on the most recent fetch.
        self.failures: dict[str, str] = {}
        self.filtered = 0

    def fetch(self, search: SearchConfig, limit: int | None = None) -> list[RawJob]:
        jobs: list[RawJob] = []
        self.failures = {}
        self.filtered = 0
        for board in self.boards:
            try:
                payload = self._get_board(board.token)
            except httpx.HTTPError as exc:
                self.failures[board.token] = board_error(exc)
                continue
            jobs.extend(parse_greenhouse(payload, board.display()))
        before = len(jobs)
        jobs = relevance_gate(jobs, search)
        self.filtered = before - len(jobs)
        return jobs[:limit] if limit is not None else jobs

    def _get_board(self, token: str) -> dict:
        return fetch_greenhouse_board(token)
