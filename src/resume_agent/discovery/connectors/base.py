from dataclasses import dataclass, field
from datetime import datetime
from collections.abc import Callable
from typing import Literal, Protocol

import httpx

from resume_agent.discovery.search_config import SearchConfig


def board_error(exc: httpx.HTTPError) -> str:
    """A compact reason for a per-board fetch failure (e.g. 'HTTP 404').

    Shared by company-ATS connectors (Greenhouse, Lever) that fan out over many
    boards and isolate each one, recording why a board was skipped.
    """
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return f"HTTP {status}" if status else type(exc).__name__


def http_failure(exc: Exception) -> str | None:
    """An ``on_error`` policy for connectors that isolate only HTTP failures.

    Records a compact reason for an ``httpx.HTTPError`` and re-raises anything
    else (returning ``None`` tells :func:`harvest` to propagate).
    """
    return board_error(exc) if isinstance(exc, httpx.HTTPError) else None


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
    stale_company: str | None = None
    company_provenance: Literal[
        "provider", "configured", "token", "fixed", "unknown"
    ] = "unknown"


def provenance_for(provider_value: str | None) -> Literal["provider", "token"]:
    """``"provider"`` when a provider-owned field carried a name, else ``"token"``."""
    return "provider" if provider_value else "token"


SkipSeen = Callable[[RawJob], bool]


@dataclass
class FetchResult:
    """What a connector's ``fetch`` returns: the kept jobs, the units that failed
    (key -> reason), and how many jobs the relevance gate dropped.

    Replaces the duck-typed ``.failures`` / ``.filtered`` attributes the runner and
    CLI used to read off the connector instance.
    """

    jobs: list[RawJob]
    failures: dict[str, str] = field(default_factory=dict)
    filtered: int = 0


class Connector(Protocol):
    """A job source behind the shared fetch seam."""

    name: str

    # Whether fetch() may run on a worker thread alongside other connectors.
    # Browser-driven connectors opt out; they are serialized among themselves.
    @property
    def concurrent_fetch(self) -> bool:
        """Whether this connector may fetch alongside other connectors."""
        ...

    def fetch(
        self,
        search: SearchConfig,
        limit: int | None = None,
        skip_seen: SkipSeen | None = None,
    ) -> FetchResult: ...
