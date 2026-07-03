import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from sqlmodel import Session

from resume_agent.concurrency import Result, gather_isolated
from resume_agent.config import get_settings
from resume_agent.discovery.connectors.base import Connector, FetchResult
from resume_agent.discovery.connectors.telemetry import record_run
from resume_agent.discovery.ingest import ingest_jobs_with_outcomes
from resume_agent.discovery.known_jobs import build_known_index, make_skip_seen
from resume_agent.discovery.search_config import SearchConfig
from resume_agent.progress import ProgressReporter


@dataclass
class PullReport:
    """Per-connector outcome of a pull: jobs added, and which units were skipped.

    Carries the failures the CLI used to re-read off each connector instance, so
    the duck-typed side-channel is gone from the runner and the CLI alike.
    """

    totals: dict[str, int] = field(default_factory=dict)
    upgraded: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)
    failures: dict[str, dict[str, str]] = field(default_factory=dict)
    changed_raw_job_ids: list[int] = field(default_factory=list)


def _run_note(
    result: FetchResult,
    added_count: int,
    upgraded_count: int,
    skipped_count: int,
) -> str | None:
    """Non-fatal note: upgrades, duplicate skips, failed sub-sources, and filters."""
    if (
        not result.filtered
        and not result.failures
        and not upgraded_count
        and not skipped_count
    ):
        return None
    parts: list[str] = [f"+{added_count} added"]
    if upgraded_count:
        parts.append(f"{upgraded_count} upgraded")
    if skipped_count:
        parts.append(f"{skipped_count} skipped")
    if result.filtered:
        parts.append(f"filtered {result.filtered} off-target")
    if result.failures:
        items = ", ".join(
            f"{name} ({reason})" for name, reason in result.failures.items()
        )
        parts.append(f"failed {len(result.failures)} source(s): {items}")
    return "; ".join(parts)


def _pull_result(report: PullReport) -> dict[str, object]:
    return {
        "totals": report.totals,
        "upgraded": report.upgraded,
        "skipped": report.skipped,
        "failures": report.failures,
    }


def _fetch_all(
    connectors: Sequence[Connector],
    search: SearchConfig,
    limit: int | None,
    skip_seen,
) -> list[Result[FetchResult]]:
    """Fetch every connector concurrently on worker threads (their APIs are sync
    and network-bound). Browser-driven connectors (concurrent_fetch=False) are
    serialized among themselves via one lock. Results come back in input order
    with failures isolated, so ingest can stay serial and canonical-ordered."""
    sem = asyncio.Semaphore(get_settings().pull_concurrency)
    browser_lock = asyncio.Lock()

    async def fetch_one(connector: Connector) -> FetchResult:
        if getattr(connector, "concurrent_fetch", True):
            async with sem:
                return await asyncio.to_thread(
                    connector.fetch, search, limit=limit, skip_seen=skip_seen
                )
        async with browser_lock:
            return await asyncio.to_thread(
                connector.fetch, search, limit=limit, skip_seen=skip_seen
            )

    return asyncio.run(gather_isolated(connectors, fetch_one))


def run_pull(
    session: Session,
    connectors: Sequence[Connector],
    search: SearchConfig,
    telemetry_path: str | Path,
    limit: int | None = None,
    reporter: ProgressReporter | None = None,
    finish: bool = True,
    skip_known: bool = True,
) -> PullReport:
    """Fetch every connector concurrently, then ingest serially in canonical
    (connector-list) order, isolating each connector's failures.

    Progress is connector-granular: the total job count is unknown until each
    connector returns, so the bar advances per connector and carries a running
    ``added`` count rather than a (fabricated) per-job percentage.
    """
    report = PullReport()
    skip_seen = make_skip_seen(build_known_index(session)) if skip_known else None
    if reporter:
        reporter.begin(total=len(connectors), label="Fetching sources", added=0)
    fetches = _fetch_all(connectors, search, limit, skip_seen)
    added_total = 0
    for index, (connector, fetched) in enumerate(zip(connectors, fetches), 1):
        if reporter:
            reporter.step(index - 1, label=f"Ingesting {connector.name}")
        if not fetched.ok or fetched.value is None:
            exc = fetched.error
            record_run(
                telemetry_path,
                connector.name,
                added=0,
                error=f"{type(exc).__name__}: {exc}" if exc else "fetch failed",
            )
            if reporter:
                reporter.step(index, added=added_total, result=_pull_result(report))
            continue
        result = fetched.value
        try:
            summary = ingest_jobs_with_outcomes(session, result.jobs)
            added_count = summary.added.get(connector.name, sum(summary.added.values()))
            upgraded_count = summary.upgraded.get(
                connector.name, sum(summary.upgraded.values())
            )
            skipped_count = summary.skipped.get(
                connector.name, sum(summary.skipped.values())
            )
            report.totals[connector.name] = added_count
            report.upgraded[connector.name] = upgraded_count
            report.skipped[connector.name] = skipped_count
            report.changed_raw_job_ids.extend(summary.changed_raw_job_ids)
            added_total += added_count
            if result.failures:
                report.failures[connector.name] = result.failures
            record_run(
                telemetry_path,
                connector.name,
                added=added_count,
                error=_run_note(result, added_count, upgraded_count, skipped_count),
            )
        except Exception as exc:
            session.rollback()
            record_run(
                telemetry_path,
                connector.name,
                added=0,
                error=f"{type(exc).__name__}: {exc}",
            )
        if reporter:
            reporter.step(index, added=added_total, result=_pull_result(report))
    if reporter and finish:
        reporter.done(added=added_total, result=_pull_result(report))
    return report
