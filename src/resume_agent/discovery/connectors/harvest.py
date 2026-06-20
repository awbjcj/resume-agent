"""The harvest seam: fan out over a connector's units, isolate per-unit failures,
then gate and cap the union.

Five connectors used to copy this loop (reset failures/filtered, iterate, isolate
``httpx.HTTPError``, relevance-gate, count filtered, truncate to limit). It now
lives here once. Single-call connectors (adzuna, remoteok) reuse only the tail,
``gate_and_limit``.
"""

from typing import Callable, Iterable, TypeVar

from resume_agent.discovery.connectors.base import FetchResult, RawJob
from resume_agent.discovery.connectors.text import relevance_gate
from resume_agent.discovery.search_config import SearchConfig

# Re-exported so callers can reach the connector result type from the harvest seam.
__all__ = ["FetchResult", "gate_and_limit", "harvest"]

U = TypeVar("U")


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
