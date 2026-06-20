from dataclasses import dataclass, field
from pathlib import Path

from sqlmodel import Session

from resume_agent.discovery.connectors.base import Connector, FetchResult
from resume_agent.discovery.connectors.telemetry import record_run
from resume_agent.discovery.ingest import ingest_jobs_with_outcomes
from resume_agent.discovery.search_config import SearchConfig


@dataclass
class PullReport:
    """Per-connector outcome of a pull: jobs added, and which units were skipped.

    Carries the failures the CLI used to re-read off each connector instance, so
    the duck-typed side-channel is gone from the runner and the CLI alike.
    """

    totals: dict[str, int] = field(default_factory=dict)
    failures: dict[str, dict[str, str]] = field(default_factory=dict)


def _run_note(result: FetchResult, added_count: int, upgraded_count: int) -> str | None:
    """Non-fatal note: upgrades, skipped sub-sources, and off-target jobs filtered."""
    if not result.filtered and not result.failures and not upgraded_count:
        return None
    parts: list[str] = [f"+{added_count} added"]
    if upgraded_count:
        parts.append(f"{upgraded_count} upgraded")
    if result.filtered:
        parts.append(f"filtered {result.filtered} off-target")
    if result.failures:
        items = ", ".join(f"{name} ({reason})" for name, reason in result.failures.items())
        parts.append(f"skipped {len(result.failures)} source(s): {items}")
    return "; ".join(parts)


def run_pull(
    session: Session,
    connectors: list[Connector],
    search: SearchConfig,
    telemetry_path: str | Path,
    limit: int | None = None,
) -> PullReport:
    """Fetch + ingest each connector in order, isolating failures."""
    report = PullReport()
    for connector in connectors:
        try:
            result = connector.fetch(search, limit=limit)
            summary = ingest_jobs_with_outcomes(session, result.jobs)
            added_count = summary.added.get(connector.name, sum(summary.added.values()))
            upgraded_count = summary.upgraded.get(connector.name, sum(summary.upgraded.values()))
            report.totals[connector.name] = added_count
            if result.failures:
                report.failures[connector.name] = result.failures
            record_run(
                telemetry_path,
                connector.name,
                added=added_count,
                error=_run_note(result, added_count, upgraded_count),
            )
        except Exception as exc:
            record_run(telemetry_path, connector.name, added=0, error=f"{type(exc).__name__}: {exc}")
    return report
