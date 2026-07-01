import httpx

from resume_agent.discovery.connectors.base import (
    FetchResult,
    RawJob,
    SkipSeen,
    http_failure,
)
from resume_agent.discovery.connectors.config import LeverBoard
from resume_agent.discovery.connectors.dates import parse_epoch_millis
from resume_agent.discovery.connectors.harvest import harvest
from resume_agent.discovery.connectors.text import html_to_markdown, primary_location
from resume_agent.discovery.search_config import SearchConfig

_BASE = "https://api.lever.co/v0/postings"


def fetch_lever_board(token: str, search: SearchConfig | None = None) -> list:
    """GET a Lever board's postings array in JSON mode."""
    params = {"mode": "json"}
    location = primary_location(search) if search is not None else ""
    if location:
        params["location"] = location
    resp = httpx.get(f"{_BASE}/{token}", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _assemble_jd(item: dict) -> str:
    """Stitch a Lever posting's opening, list sections, and closing into text.

    Lever splits a JD into ``description`` (opening), ``lists`` (the
    Responsibilities/Requirements bullets), and ``additional`` (closing). The
    list sections carry the skill-bearing content, so all three are joined and
    run through ``html_to_text`` once — mirroring the Greenhouse connector.
    """
    parts: list[str] = [item.get("description") or ""]
    for section in item.get("lists") or []:
        heading = section.get("text")
        if heading:
            parts.append(f"<h3>{heading}</h3>")
        parts.append(section.get("content") or "")
    parts.append(item.get("additional") or "")
    return html_to_markdown("\n".join(part for part in parts if part))


def parse_lever(payload: list, company: str) -> list[RawJob]:
    """Map a Lever board postings array to RawJobs."""
    jobs: list[RawJob] = []
    for item in payload:
        categories = item.get("categories") or {}
        jobs.append(
            RawJob(
                source="lever",
                url=item.get("hostedUrl"),
                company=company,
                title=item.get("text"),
                location=categories.get("location"),
                jd_text=_assemble_jd(item),
                posted_at=parse_epoch_millis(item.get("createdAt")),
            )
        )
    return jobs


class LeverConnector:
    """Pulls every open role from each configured Lever board, then filters.

    Boards are isolated: one bad token (a 404, a timeout) is recorded in
    ``failures`` and skipped, so the remaining boards still contribute jobs.
    """

    name = "lever"

    def __init__(self, boards: list[LeverBoard]):
        self.boards = boards

    def fetch(
        self,
        search: SearchConfig,
        limit: int | None = None,
        skip_seen: SkipSeen | None = None,
    ) -> FetchResult:
        return harvest(
            self.boards,
            lambda board: parse_lever(
                self._get_board(board.token, search), board.display()
            ),
            search=search,
            limit=limit,
            key=lambda board: board.token,
            on_error=http_failure,
        )

    def _get_board(self, token: str, search: SearchConfig) -> list:
        return fetch_lever_board(token, search)
