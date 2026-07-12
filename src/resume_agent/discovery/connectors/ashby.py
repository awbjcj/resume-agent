import httpx

from resume_agent.discovery.connectors.base import (
    FetchResult,
    RawJob,
    SkipSeen,
    http_failure,
)
from resume_agent.discovery.connectors.config import AshbyBoard
from resume_agent.discovery.connectors.dates import parse_iso_datetime
from resume_agent.discovery.connectors.harvest import harvest
from resume_agent.discovery.connectors.text import html_to_markdown
from resume_agent.discovery.search_config import SearchConfig

_BASE = "https://api.ashbyhq.com/posting-api/job-board"


def parse_ashby(payload: dict, company: str) -> list[RawJob]:
    """Map an Ashby posting-api jobs payload to RawJobs."""
    jobs: list[RawJob] = []
    for item in payload.get("jobs", []):
        jd_text = item.get("descriptionPlain") or html_to_markdown(
            item.get("descriptionHtml", "")
        )
        jobs.append(
            RawJob(
                source="ashby",
                url=item.get("jobUrl"),
                company=company,
                title=item.get("title"),
                location=item.get("location"),
                jd_text=jd_text,
                posted_at=parse_iso_datetime(item.get("publishedAt")),
            )
        )
    return jobs


def fetch_ashby_board(token: str) -> dict:
    """GET an Ashby job board's postings payload."""
    resp = httpx.get(f"{_BASE}/{token}", timeout=30)
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
