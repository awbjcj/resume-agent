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
        meta=snapshot.meta,
    )


async def run_events(
    mgr, run_id: str, *, poll_interval: float = 0.5
) -> AsyncIterator[dict]:
    """Yield sse-starlette event dicts until the run reaches a terminal state.

    Emits an event whenever the projected RunOut changes, plus a final event on
    the terminal record, then stops (closing the stream). A missing record yields
    a single not-found-shaped terminal event so the client never hangs.

    Two things this deliberately does **not** do any more:

    * It does not sleep out the full poll interval between writes. The run's
      ``StreamNotifier`` — the same fanout ``RunStreamSink`` readers use — wakes
      it as soon as a progress or terminal write lands, so a run that finishes
      in 50 ms delivers its terminal event in about 50 ms rather than up to 500.
      The interval survives as the dropped-notification fallback, which is what
      keeps the notifier from ever owning stream truth.
    * It does not read the snapshot on the event loop. That read is a file read
      from a mounted volume; doing it inline let one slow volume stall the API
      loop for *every* connected client.
    """
    notifier = getattr(mgr, "notifier", None)
    wakeup = notifier(run_id) if callable(notifier) else None
    event = wakeup.subscribe() if wakeup is not None else None
    try:
        last: str | None = None
        while True:
            # Clear before reading, so a write that lands during the read is
            # still seen as a pending wakeup rather than being swallowed.
            if event is not None:
                event.clear()
            snapshot = await asyncio.to_thread(mgr.get, run_id)
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
            if event is None:
                await asyncio.sleep(poll_interval)
                continue
            try:
                await asyncio.wait_for(event.wait(), timeout=poll_interval)
            except (TimeoutError, asyncio.TimeoutError):
                pass
    finally:
        if wakeup is not None and event is not None:
            wakeup.unsubscribe(event)
