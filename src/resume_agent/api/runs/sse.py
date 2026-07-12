"""Shared record -> RunOut projection (used by GET /runs/{id} and the SSE stream)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from resume_agent.api.runs.models import RunSnapshot
from resume_agent.api.schemas.runs import RunOut


def record_to_run(snapshot: RunSnapshot) -> RunOut:
    return RunOut(
        run_id=snapshot.run_id,
        kind=snapshot.kind,
        state=snapshot.state,
        label=snapshot.label,
        percent=snapshot.percent,
        current=snapshot.current,
        total=snapshot.total,
        eta_text=snapshot.eta_text,
        result=snapshot.result,
        error=snapshot.error,
        error_code=snapshot.error_code,
    )


async def run_events(
    mgr, run_id: str, *, poll_interval: float = 0.5
) -> AsyncIterator[dict]:
    """Yield sse-starlette event dicts until the run reaches a terminal state.

    Emits an event whenever the projected RunOut changes, plus a final event on
    the terminal record, then stops (closing the stream). A missing record yields
    a single not-found-shaped terminal event so the client never hangs.
    """
    last: str | None = None
    while True:
        snapshot = mgr.get(run_id)
        if snapshot is None:
            yield {
                "data": json.dumps(
                    {"state": "error", "error": "run not found", "percent": 0}
                )
            }
            return
        run = record_to_run(snapshot)
        payload = run.model_dump(mode="json", by_alias=True)
        serialized = json.dumps(payload)
        if serialized != last:
            yield {"data": serialized}
            last = serialized
        if run.state in ("done", "error", "cancelled"):
            return
        await asyncio.sleep(poll_interval)
