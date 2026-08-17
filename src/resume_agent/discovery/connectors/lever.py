
from resume_agent.discovery.connectors import http as board

from resume_agent.discovery.connectors.base import (
    FetchResult,
    RawJob,
    SkipSeen,
    http_failure,
)
from resume_agent.discovery.connectors.config import LeverBoard
from resume_agent.discovery.connectors.dates import parse_epoch_millis
from resume_agent.discovery.connectors.harvest import harvest
from resume_agent.discovery.connectors.text import html_to_markdown, join_locations
from resume_agent.discovery.search_config import SearchConfig

_BASE = "https://api.lever.co/v0/postings"

# Lever's salaryRange.interval enum -> the suffix a pay band reads with.
# Verified live across the zoox and matchgroup boards (328 postings):
# per-year-salary 282, per-hour-wage 4.
_SALARY_INTERVALS = {
    "per-year-salary": "per year",
    "per-month-salary": "per month",
    "per-week-salary": "per week",
    "per-day-wage": "per day",
    "per-hour-wage": "per hour",
}


def _location(item: dict) -> str | None:
    categories = item.get("categories") or {}
    return join_locations(
        [categories.get("location"), *(categories.get("allLocations") or [])]
    )


def _amount(value) -> str | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return f"{value:,.0f}"


def _salary_line(item: dict) -> str | None:
    """Render ``salaryRange`` the way the posting's pay band reads."""
    salary = item.get("salaryRange")
    if not isinstance(salary, dict):
        return None
    low, high = _amount(salary.get("min")), _amount(salary.get("max"))
    span = f"{low} - {high}" if low and high else (low or high)
    if not span:
        return None
    currency = salary.get("currency")
    interval = _SALARY_INTERVALS.get(str(salary.get("interval") or "").lower())
    return "Compensation: " + " ".join(
        part for part in (currency, span, interval) if part
    )


def _sidebar_lines(item: dict) -> list[str]:
    """The facts a Lever posting shows beside its body, as text lines.

    Location, workplace type, commitment, department/team, level, and the pay
    band live in dedicated API fields rather than in the JD html, so they are
    rendered as ``Label: value`` lines prepended to jd_text -- the same shape
    ``ashby.parse_ashby`` and ``greenhouse.parse_greenhouse`` use -- for the
    relevance gate, criteria extraction, and tailoring to read.
    """
    categories = item.get("categories") or {}
    lines: list[str] = []

    location = categories.get("location")
    # ``allLocations`` repeats the primary location, so only the extras are
    # additive (46 of 328 live postings list more than one).
    extras = [
        other
        for other in categories.get("allLocations") or []
        if other and other != location
    ]
    if location and extras:
        lines.append(f"Location: {location} (also: {', '.join(extras)})")
    elif location:
        lines.append(f"Location: {location}")

    if workplace := item.get("workplaceType"):
        # The API serves these lowercase ("hybrid", "onsite", "remote").
        lines.append(f"Workplace Type: {str(workplace).capitalize()}")

    if commitment := categories.get("commitment"):
        lines.append(f"Employment Type: {commitment}")

    department, team = categories.get("department"), categories.get("team")
    if department and team and department != team:
        lines.append(f"Department: {department} ({team})")
    elif department or team:
        lines.append(f"Department: {department or team}")

    if level := categories.get("level"):
        lines.append(f"Level: {level}")

    if salary := _salary_line(item):
        lines.append(salary)

    return lines


def fetch_lever_board(token: str) -> list:
    """GET a Lever board's full postings array in JSON mode.

    No server-side ``location`` filter: Lever's ``?location=`` param is an exact,
    case-sensitive match against a posting's ``categories.location``, so any
    near-miss (or a posting with no location) silently drops the whole board.
    Like Greenhouse and Ashby, we fetch every posting in one GET and let the
    local relevance gate decide.
    """
    resp = board.get(f"{_BASE}/{token}", params={"mode": "json"})
    resp.raise_for_status()
    return resp.json()


def fetch_lever_posting(token: str, posting_id: str) -> dict:
    """GET a single Lever posting by id -- same shape as one ``fetch_lever_board`` item."""
    resp = board.get(f"{_BASE}/{token}/{posting_id}", params={"mode": "json"})
    resp.raise_for_status()
    return resp.json()


def _assemble_jd(item: dict) -> str:
    """Stitch a Lever posting's opening, list sections, and closing into text.

    Lever splits a JD into ``description`` (opening), ``lists`` (the
    Responsibilities/Requirements bullets), ``salaryDescription`` (the pay and
    benefits prose), and ``additional`` (closing). The list sections carry the
    skill-bearing content, so all are joined and run through ``html_to_text``
    once — mirroring the Greenhouse connector.

    ``salaryDescription`` is a *separate* section, not a duplicate of anything
    already assembled: measured against the live zoox board, 212 of 244
    postings carry one and **none** of those texts appear anywhere in the other
    three fields, so reading only description/lists/additional silently dropped
    every posting's pay-and-benefits narrative. It sits before ``additional``
    so the closing boilerplate stays last, matching the rendered page.
    """
    parts: list[str] = [item.get("description") or ""]
    for section in item.get("lists") or []:
        heading = section.get("text")
        if heading:
            parts.append(f"<h3>{heading}</h3>")
        parts.append(section.get("content") or "")
    parts.append(item.get("salaryDescription") or "")
    parts.append(item.get("additional") or "")
    return html_to_markdown("\n".join(part for part in parts if part))


def parse_lever(payload: list, company: str) -> list[RawJob]:
    """Map a Lever board postings array to RawJobs."""
    jobs: list[RawJob] = []
    for item in payload:
        jd_text = _assemble_jd(item)
        if sidebar := _sidebar_lines(item):
            jd_text = "\n".join(sidebar) + ("\n\n" + jd_text if jd_text else "")
        jobs.append(
            RawJob(
                source="lever",
                url=item.get("hostedUrl"),
                company=company,
                title=item.get("text"),
                location=_location(item),
                jd_text=jd_text,
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
    concurrent_fetch = True

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
            lambda board: parse_lever(self._get_board(board.token), board.display()),
            search=search,
            limit=limit,
            key=lambda board: board.token,
            on_error=http_failure,
            skip_seen=skip_seen,
            unit_limit=lambda board: board.limit,
        )

    def _get_board(self, token: str) -> list:
        return fetch_lever_board(token)
