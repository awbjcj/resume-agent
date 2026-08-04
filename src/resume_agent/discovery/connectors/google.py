"""Google Careers via the public results page's embedded jobs callback.

The old ``careers.google.com/api/v3`` endpoint is dead. The current results
page embeds full job rows in ``AF_initDataCallback`` key ``ds:1``; a shape
change raises so the companies connector can isolate and report the source.
"""

import json
import re
from collections.abc import Sequence
from datetime import datetime, timezone


from resume_agent.discovery.connectors import http as board

from resume_agent.discovery.connectors.base import RawJob, SkipSeen
from resume_agent.discovery.connectors.detect import AtsTarget
from resume_agent.discovery.connectors.harvest import gate_and_limit
from resume_agent.discovery.connectors.text import html_to_markdown, primary_search_term
from resume_agent.discovery.search_config import SearchConfig

_RESULTS_URL = "https://www.google.com/about/careers/applications/jobs/results"
_MAX_PAGES = 20
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) resume-agent",
}

_CALLBACK = re.compile(r"AF_initDataCallback\((\{.*?\})\);", re.DOTALL)
_JOBS_KEY = re.compile(r"\bkey:\s*['\"]ds:1['\"]")
_CALLBACK_DATA = re.compile(
    r"\bdata:\s*(\[.*\])\s*,\s*sideChannel\s*:", re.DOTALL
)


def extract_job_rows(html: str) -> list[list]:
    """Return rows from the pinned jobs callback, distinguishing empty from drift."""
    for callback in _CALLBACK.findall(html):
        if not _JOBS_KEY.search(callback):
            continue
        match = _CALLBACK_DATA.search(callback)
        if match is None:
            raise ValueError("Google jobs blob has no data payload")
        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError as exc:
            raise ValueError("Google jobs blob data is not valid JSON") from exc
        if (
            not isinstance(data, list)
            or len(data) < 4
            or not isinstance(data[0], list)
            or not isinstance(data[2], int)
            or not isinstance(data[3], int)
        ):
            raise ValueError("Google jobs blob has an unexpected shape")
        return data[0]
    raise ValueError("Google jobs blob ds:1 callback is missing")


def _html_cell(row: list, index: int) -> str:
    cell = row[index] if index < len(row) else None
    if isinstance(cell, list) and len(cell) >= 2 and isinstance(cell[1], str):
        return cell[1]
    return ""


def _first_location(row: list) -> str | None:
    cell = row[9] if len(row) > 9 else None
    if isinstance(cell, list) and cell and isinstance(cell[0], list) and cell[0]:
        display = cell[0][0]
        if isinstance(display, str):
            return display
    return None


def _posted_at(row: list) -> datetime | None:
    cell = row[12] if len(row) > 12 else None
    if isinstance(cell, list) and cell and isinstance(cell[0], (int, float)):
        try:
            return datetime.fromtimestamp(cell[0], tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    return None


def parse_job_rows(rows: Sequence[object]) -> list[RawJob]:
    """Map live callback rows to jobs, skipping individually malformed rows."""
    jobs: list[RawJob] = []
    for row in rows:
        if not isinstance(row, list) or len(row) < 2:
            continue
        job_id = str(row[0] or "")
        title = row[1]
        if not job_id or not isinstance(title, str):
            continue
        description = "\n".join(
            part
            for part in (_html_cell(row, 10), _html_cell(row, 4), _html_cell(row, 3))
            if part
        )
        jobs.append(
            RawJob(
                source="google",
                url=f"{_RESULTS_URL}/{job_id}",
                company="Google",
                title=title,
                location=_first_location(row),
                jd_text=html_to_markdown(description),
                posted_at=_posted_at(row),
            )
        )
    return jobs


def fetch_google(
    target: AtsTarget,
    search: SearchConfig,
    limit: int | None = None,
    skip_seen: SkipSeen | None = None,
) -> list[RawJob]:
    jobs: list[RawJob] = []
    query = primary_search_term(search)
    for page_num in range(1, _MAX_PAGES + 1):
        response = board.get(
            _RESULTS_URL,
            params={"q": query, "page": page_num},
            headers=_HEADERS,
        )
        response.raise_for_status()
        batch = parse_job_rows(extract_job_rows(response.text))
        if not batch:
            break
        jobs.extend(batch)
        if limit is not None:
            kept, _ = gate_and_limit(jobs, search, limit, skip_seen)
            if len(kept) >= limit:
                return kept
    if limit is not None:
        jobs, _ = gate_and_limit(jobs, search, limit, skip_seen)
    return jobs
