import httpx

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.connectors.config import GreenhouseBoard
from resume_agent.discovery.connectors.text import filter_by_search, html_to_text
from resume_agent.discovery.search_config import SearchConfig

_BASE = "https://boards-api.greenhouse.io/v1/boards"


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
            )
        )
    return jobs


class GreenhouseConnector:
    """Pulls every open role from each configured Greenhouse board, then filters."""

    name = "greenhouse"

    def __init__(self, boards: list[GreenhouseBoard]):
        self.boards = boards

    def fetch(self, search: SearchConfig, limit: int | None = None) -> list[RawJob]:
        jobs: list[RawJob] = []
        for board in self.boards:
            jobs.extend(parse_greenhouse(self._get_board(board.token), board.display()))
        jobs = filter_by_search(jobs, search)
        return jobs[:limit] if limit is not None else jobs

    def _get_board(self, token: str) -> dict:
        resp = httpx.get(f"{_BASE}/{token}/jobs", params={"content": "true"}, timeout=30)
        resp.raise_for_status()
        return resp.json()
