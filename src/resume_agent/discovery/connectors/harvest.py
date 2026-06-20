"""The harvest seam: fan out over a connector's units, isolate per-unit failures,
then gate and cap the union.

Five connectors used to copy this loop (reset failures/filtered, iterate, isolate
``httpx.HTTPError``, relevance-gate, count filtered, truncate to limit). It now
lives here once. Single-call connectors (adzuna, remoteok) reuse only the tail,
``gate_and_limit``.
"""

from typing import Callable, Iterable, TypeVar

import httpx

from resume_agent.discovery.connectors.base import FetchResult, RawJob
from resume_agent.discovery.connectors.text import relevance_gate, title_relevance_gate
from resume_agent.discovery.search_config import SearchConfig

# Re-exported so callers can reach the connector result type from the harvest seam.
__all__ = ["FetchResult", "gate_and_limit", "harvest", "harvest_detailed"]

U = TypeVar("U")
T = TypeVar("T", bound=RawJob)


def gate_and_limit(
    jobs: list[RawJob], search: SearchConfig, limit: int | None
) -> tuple[list[RawJob], int]:
    """Relevance-gate the jobs, report how many were dropped, then cap to ``limit``."""
    before = len(jobs)
    gated = relevance_gate(jobs, search)
    filtered = before - len(gated)
    return (gated[:limit] if limit is not None else gated), filtered


def harvest(
    units: Iterable[U],
    produce: Callable[[U], list[RawJob]],
    *,
    search: SearchConfig,
    limit: int | None,
    key: Callable[[U], str],
    on_error: Callable[[Exception], str | None],
) -> FetchResult:
    """Fan out over ``units``, isolating each unit's failure, then gate and cap.

    ``produce`` turns one unit into RawJobs. When it raises, ``on_error`` decides:
    a returned string records ``failures[key(unit)] = reason`` and continues; ``None``
    re-raises (the connector does not tolerate this failure).
    """
    jobs: list[RawJob] = []
    failures: dict[str, str] = {}
    for unit in units:
        try:
            jobs.extend(produce(unit))
        except Exception as exc:  # noqa: BLE001 — on_error decides record vs propagate
            reason = on_error(exc)
            if reason is None:
                raise
            failures[key(unit)] = reason
    jobs, filtered = gate_and_limit(jobs, search, limit)
    return FetchResult(jobs=jobs, failures=failures, filtered=filtered)


def harvest_detailed(
    rows: Iterable[T],
    fetch_detail: Callable[[T], dict | None],
    apply_detail: Callable[[T, dict], None],
    *,
    search: SearchConfig,
    limit: int | None,
) -> list[RawJob]:
    """The N+1 list-then-detail dance shared by Workday and Tesla.

    Each row arrives with title + location but no JD. Title-gate before the
    expensive detail fetch; ``fetch_detail`` returns the detail payload (or
    ``None`` when the row has no detail to fetch) and may raise ``httpx.HTTPError``
    — one stale detail endpoint skips its row, never the whole batch.
    ``apply_detail`` fills the JD (and any sharper url/location) before the full
    relevance gate runs on the now-complete row.
    """
    jobs: list[RawJob] = []
    for row in rows:
        if not title_relevance_gate([row], search):
            continue
        try:
            detail = fetch_detail(row)
        except httpx.HTTPError:
            continue
        if detail is None:
            continue
        apply_detail(row, detail)
        if relevance_gate([row], search):
            jobs.append(row)
            if limit is not None and len(jobs) >= limit:
                break
    return jobs
