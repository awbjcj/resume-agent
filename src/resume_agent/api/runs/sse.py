"""Shared record -> RunOut projection (used by GET /runs/{id} and the SSE stream)."""

from __future__ import annotations

from resume_agent.api.schemas.runs import RunOut
from resume_agent.progress import progress_stats


def record_to_run(run_id: str, record: dict) -> RunOut:
    stats = progress_stats(record)
    return RunOut(
        run_id=run_id,
        kind=str(record.get("kind") or ""),
        state=stats.state if record.get("state") != "pending" else "pending",
        label=stats.label,
        percent=stats.pct,
        current=stats.current,
        total=stats.total,
        eta_text=stats.eta_text,
        result=record.get("result"),
        error=stats.error,
    )
