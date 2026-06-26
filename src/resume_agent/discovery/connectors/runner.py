from dataclasses import dataclass, field
from pathlib import Path

from sqlmodel import Session

from resume_agent.discovery.connectors.base import Connector, FetchResult
from resume_agent.discovery.connectors.telemetry import record_run
from resume_agent.discovery.ingest import ingest_jobs_with_outcomes
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
    if not result.filtered and not result.failures and not upgraded_count and not skipped_count:
        return None
    parts: list[str] = [f"+{added_count} added"]
    if upgraded_count:
        parts.append(f"{upgraded_count} upgraded")
    if skipped_count:
        parts.append(f"{skipped_count} skipped")
    if result.filtered:
        parts.append(f"filtered {result.filtered} off-target")
    if result.failures:
        items = ", ".join(f"{name} ({reason})" for name, reason in result.failures.items())
        parts.append(f"failed {len(result.failures)} source(s): {items}")
    return "; ".join(parts)


def _pull_result(report: PullReport) -> dict[str, object]:
    return {
        "totals": report.totals,
        "upgraded": report.upgraded,
        "skipped": report.skipped,
        "failures": report.failures,
    }


def run_pull(
    session: Session,
    connectors: list[Connector],
    search: SearchConfig,
    telemetry_path: str | Path,
    limit: int | None = None,
    reporter: ProgressReporter | None = None,
    finish: bool = True,
) -> PullReport:
    """Fetch + ingest each connector in order, isolating failures.

    Progress is connector-granular: the total job count is unknown until each
    connector returns, so the bar advances per connector and carries a running
    ``added`` count rather than a (fabricated) per-job percentage.
    """
    report = PullReport()
    if reporter:
        reporter.begin(total=len(connectors), label="Starting", added=0)
    added_total = 0
    for index, connector in enumerate(connectors, 1):
        if reporter:
            reporter.step(index - 1, label=f"Pulling {connector.name}")
        try:
            result = connector.fetch(search, limit=limit)
            summary = ingest_jobs_with_outcomes(session, result.jobs)
            added_count = summary.added.get(connector.name, sum(summary.added.values()))
            upgraded_count = summary.upgraded.get(connector.name, sum(summary.upgraded.values()))
            skipped_count = summary.skipped.get(connector.name, sum(summary.skipped.values()))
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
            record_run(telemetry_path, connector.name, added=0, error=f"{type(exc).__name__}: {exc}")
        if reporter:
            reporter.step(index, added=added_total, result=_pull_result(report))
    if reporter and finish:
        reporter.done(added=added_total, result=_pull_result(report))
    return report
