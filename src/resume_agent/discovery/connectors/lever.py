import httpx

from resume_agent.discovery.connectors.base import RawJob, board_error
from resume_agent.discovery.connectors.config import LeverBoard
from resume_agent.discovery.connectors.dates import parse_epoch_millis
from resume_agent.discovery.connectors.text import html_to_text, relevance_gate
from resume_agent.discovery.search_config import SearchConfig

_BASE = "https://api.lever.co/v0/postings"


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
    return html_to_text("\n".join(part for part in parts if part))


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
            jobs.extend(parse_lever(payload, board.display()))
        before = len(jobs)
        jobs = relevance_gate(jobs, search)
        self.filtered = before - len(jobs)
        return jobs[:limit] if limit is not None else jobs

    def _get_board(self, token: str) -> list:
        resp = httpx.get(f"{_BASE}/{token}", params={"mode": "json"}, timeout=30)
        resp.raise_for_status()
        return resp.json()
