from dataclasses import dataclass
from typing import Protocol

from resume_agent.discovery.search_config import SearchConfig


@dataclass
class RawJob:
    """A single job as a connector emits it, ready for ingest."""

    source: str
    url: str | None
    company: str | None
    title: str | None
    location: str | None
    jd_text: str


class Connector(Protocol):
    """A job source behind the shared fetch seam."""

    name: str

    def fetch(self, search: SearchConfig, limit: int | None = None) -> list[RawJob]: ...
