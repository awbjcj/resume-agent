"""The harvest seam: fan out over a connector's units, isolate per-unit failures,
then gate and cap each unit.

Five connectors used to copy this loop (reset failures/filtered, iterate, isolate
``httpx.HTTPError``, relevance-gate, count filtered, truncate to limit). It now
lives here once. Single-call connectors (adzuna, remoteok) reuse only the tail,
``gate_and_limit``.
"""

from typing import Callable, Iterable, TypeVar

import httpx

from resume_agent.discovery.connectors.base import FetchResult, RawJob, SkipSeen
from resume_agent.discovery.connectors.text import relevance_gate, title_relevance_gate
from resume_agent.discovery.search_config import SearchConfig

# Re-exported so callers can reach the connector result type from the harvest seam.
__all__ = ["FetchResult", "gate_and_limit", "harvest", "harvest_detailed"]

U = TypeVar("U")
T = TypeVar("T", bound=RawJob)


def gate_and_limit(
    jobs: list[RawJob],
    search: SearchConfig,
    limit: int | None,
    skip_seen: SkipSeen | None = None,
) -> tuple[list[RawJob], int]:
    """Relevance-gate the jobs, report how many were dropped, drop already-known
    rows, then cap to ``limit``.

    ``skip_seen`` runs after the relevance gate (so ``filtered`` still counts only
    relevance drops) and before the limit slice (so the cap fills with unseen rows).
    """
    before = len(jobs)
    gated = relevance_gate(jobs, search)
    filtered = before - len(gated)
    if skip_seen is not None:
        gated = [job for job in gated if not skip_seen(job)]
    return (gated[:limit] if limit is not None else gated), filtered


def harvest(
    units: Iterable[U],
    produce: Callable[[U], list[RawJob]],
    *,
    search: SearchConfig,
    limit: int | None,
    key: Callable[[U], str],
    on_error: Callable[[Exception], str | None],
    skip_seen: SkipSeen | None = None,
    unit_limit: Callable[[U], int | None] | None = None,
) -> FetchResult:
    """Fan out, isolate failures, then gate and cap each unit independently.

    ``produce`` turns one unit into RawJobs. When it raises, ``on_error`` decides:
    a returned string records ``failures[key(unit)] = reason`` and continues; ``None``
    re-raises (the connector does not tolerate this failure). A unit's configured
    limit overrides the global fallback. ``skip_seen`` runs before each cap.
    """
    jobs: list[RawJob] = []
    failures: dict[str, str] = {}
    filtered = 0
    for unit in units:
        try:
            produced = produce(unit)
        except Exception as exc:  # noqa: BLE001 — on_error decides record vs propagate
            reason = on_error(exc)
            if reason is None:
                raise
            failures[key(unit)] = reason
            continue
        configured_limit = unit_limit(unit) if unit_limit is not None else None
        kept, unit_filtered = gate_and_limit(
            produced,
            search,
            configured_limit if configured_limit is not None else limit,
            skip_seen,
        )
        jobs.extend(kept)
        filtered += unit_filtered
    return FetchResult(jobs=jobs, failures=failures, filtered=filtered)


def harvest_detailed(
    rows: Iterable[T],
    fetch_detail: Callable[[T], dict | None],
    apply_detail: Callable[[T, dict], None],
    *,
    search: SearchConfig,
    limit: int | None,
    skip_seen: SkipSeen | None = None,
) -> list[RawJob]:
    """The N+1 list-then-detail dance shared by Workday and Tesla.

    Each row arrives with title + location but no JD. Title-gate before the
    expensive detail fetch; ``fetch_detail`` returns the detail payload (or
    ``None`` when the row has no detail to fetch) and may raise ``httpx.HTTPError``
    — one stale detail endpoint skips its row, never the whole batch.
    ``apply_detail`` fills the JD (and any sharper url/location) before the full
    relevance gate runs on the now-complete row; if it raises on a malformed
    payload (e.g. a detail page missing its JobPosting JSON-LD) that row is
    skipped too, never the whole batch.
    """
    jobs: list[RawJob] = []
    for row in rows:
        if not title_relevance_gate([row], search):
            continue
        if skip_seen is not None and skip_seen(row):
            continue
        try:
            detail = fetch_detail(row)
        except httpx.HTTPError:
            continue
        if detail is None:
            continue
        try:
            apply_detail(row, detail)
        except (ValueError, KeyError):
            continue
        if relevance_gate([row], search):
            jobs.append(row)
            if limit is not None and len(jobs) >= limit:
                break
    return jobs
