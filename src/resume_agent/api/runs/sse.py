"""Shared record -> RunOut projection (used by GET /runs/{id} and the SSE stream)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from resume_agent.api.schemas.runs import RunOut
from resume_agent.progress import progress_stats


def record_to_run(run_id: str, record: dict) -> RunOut:
    stats = progress_stats(record)
    return RunOut(
        run_id=run_id,
        kind=str(record.get("kind") or ""),
        state=stats.state,  # progress_stats passes "pending"/"running"/"done"/"error" through
        label=stats.label,
        percent=stats.pct,
        current=stats.current,
        total=stats.total,
        eta_text=stats.eta_text,
        result=record.get("result"),
        error=stats.error,
    )


async def run_events(mgr, run_id: str, *, poll_interval: float = 0.5) -> AsyncIterator[dict]:
    """Yield sse-starlette event dicts until the run reaches a terminal state.

    Emits an event whenever the projected RunOut changes, plus a final event on
    the terminal record, then stops (closing the stream). A missing record yields
    a single not-found-shaped terminal event so the client never hangs.
    """
    last: str | None = None
    while True:
        record = mgr.get(run_id)
        if record is None:
            yield {"data": json.dumps({"state": "error", "error": "run not found", "percent": 0})}
            return
        run = record_to_run(run_id, record)
        payload = run.model_dump(mode="json", by_alias=True)
        serialized = json.dumps(payload)
        if serialized != last:
            yield {"data": serialized}
            last = serialized
        if run.state in ("done", "error"):
            return
        await asyncio.sleep(poll_interval)
