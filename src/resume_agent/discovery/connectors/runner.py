from pathlib import Path

from sqlmodel import Session

from resume_agent.discovery.connectors.base import Connector
from resume_agent.discovery.connectors.telemetry import record_run
from resume_agent.discovery.ingest import ingest_jobs
from resume_agent.discovery.search_config import SearchConfig


def _partial_failure_note(connector: Connector, count: int) -> str | None:
    """A non-fatal note about sub-sources a connector skipped (e.g. dead boards)."""
    failures: dict[str, str] | None = getattr(connector, "failures", None)
    if not failures:
        return None
    items = ", ".join(f"{name} ({reason})" for name, reason in failures.items())
    return f"+{count} added; skipped {len(failures)} source(s): {items}"


def run_pull(
    session: Session,
    connectors: list[Connector],
    search: SearchConfig,
    telemetry_path: str | Path,
    limit: int | None = None,
) -> dict[str, int]:
    """Fetch + ingest each connector in order, isolating failures."""
    totals: dict[str, int] = {}
    for connector in connectors:
        try:
            raw_jobs = connector.fetch(search, limit=limit)
            added = ingest_jobs(session, raw_jobs)
            count = added.get(connector.name, sum(added.values()))
            totals[connector.name] = count
            record_run(
                telemetry_path,
                connector.name,
                added=count,
                error=_partial_failure_note(connector, count),
            )
        except Exception as exc:
            record_run(telemetry_path, connector.name, added=0, error=f"{type(exc).__name__}: {exc}")
    return totals
