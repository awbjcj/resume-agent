"""The harvest seam: fan out over a connector's units, isolate per-unit failures,
then gate and cap each unit.

Five connectors used to copy this loop (reset failures/filtered, iterate, isolate
``httpx.HTTPError``, relevance-gate, count filtered, truncate to limit). It now
lives here once. Single-call connectors (adzuna, remoteok) reuse only the tail,
``gate_and_limit``.
"""

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
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
    transform_kept: Callable[[U, list[RawJob]], list[RawJob]] | None = None,
) -> FetchResult:
    """Fan out, isolate failures, then gate and cap each unit independently.

    ``produce`` turns one unit into RawJobs. When it raises, ``on_error`` decides:
    a returned string records ``failures[key(unit)] = reason`` and continues; ``None``
    re-raises (the connector does not tolerate this failure). A unit's configured
    limit overrides the global fallback. ``skip_seen`` runs before each cap.
    ``transform_kept`` performs optional detail enrichment only after gating,
    deduplication, and the cap, so large boards do not fetch pages that cannot
    enter the result.
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
        if transform_kept is not None:
            kept = transform_kept(unit, kept)
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
    candidates = [
        row
        for row in rows
        if title_relevance_gate([row], search)
        and not (skip_seen is not None and skip_seen(row))
    ]
    jobs: list[RawJob] = []
    concurrency = _detail_concurrency()
    start = 0
    while start < len(candidates):
        # Never fetch more details than the limit could still consume. Without
        # this, a limit=1 run would fetch a whole chunk to keep one row; with
        # it, the overshoot is bounded by what is genuinely still needed.
        size = concurrency
        if limit is not None:
            size = min(size, max(1, limit - len(jobs)))
        chunk = candidates[start : start + size]
        start += size
        for row, detail in zip(chunk, _fetch_details(chunk, fetch_detail)):
            if detail is None:
                continue
            try:
                apply_detail(row, detail)
            except (ValueError, KeyError):
                continue
            if relevance_gate([row], search):
                jobs.append(row)
                if limit is not None and len(jobs) >= limit:
                    return jobs
    return jobs


def _detail_concurrency() -> int:
    from resume_agent.config import get_settings

    return max(1, get_settings().detail_fetch_concurrency)


def _fetch_details(
    chunk: list[T], fetch_detail: Callable[[T], dict | None]
) -> list[dict | None]:
    """Fetch one chunk's details concurrently, in row order.

    The fetches are independent and network-bound, so they run on threads. A
    stale detail endpoint skips its own row and never the batch — the same
    isolation the serial loop had, kept per row rather than per batch. The
    bound is per call site, which for the two N+1 connectors means per host, so
    the existing throttle retry is not turned into a thundering herd.

    Each task runs in its **own copy** of the caller's context. A bare thread
    inherits no ``ContextVar``, which would silently drop both the run's
    connection pool and — far worse — the active ``UserContext``, so a detail
    fetch would resolve tenant paths against the wrong workspace. A copy per
    task, not one shared copy: a ``Context`` cannot be entered twice at once.
    """
    if len(chunk) == 1:
        return [_fetch_one(chunk[0], fetch_detail)]
    tasks = [(copy_context(), row) for row in chunk]
    with ThreadPoolExecutor(max_workers=len(chunk)) as pool:
        return list(
            pool.map(lambda task: task[0].run(_fetch_one, task[1], fetch_detail), tasks)
        )


def _fetch_one(row: T, fetch_detail: Callable[[T], dict | None]) -> dict | None:
    try:
        return fetch_detail(row)
    except httpx.HTTPError:
        return None
