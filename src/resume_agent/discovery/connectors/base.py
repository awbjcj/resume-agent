from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import httpx

from resume_agent.discovery.search_config import SearchConfig


def board_error(exc: httpx.HTTPError) -> str:
    """A compact reason for a per-board fetch failure (e.g. 'HTTP 404').

    Shared by company-ATS connectors (Greenhouse, Lever) that fan out over many
    boards and isolate each one, recording why a board was skipped.
    """
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return f"HTTP {status}" if status else type(exc).__name__


@dataclass
class RawJob:
    """A single job as a connector emits it, ready for ingest."""

    source: str
    url: str | None
    company: str | None
    title: str | None
    location: str | None
    jd_text: str
    posted_at: datetime | None = None


class Connector(Protocol):
    """A job source behind the shared fetch seam."""

    name: str

    def fetch(self, search: SearchConfig, limit: int | None = None) -> list[RawJob]: ...
