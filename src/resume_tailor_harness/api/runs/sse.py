"""Shared record -> RunOut projection (used by GET /runs/{id} and the SSE stream)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Protocol

from resume_tailor_harness.api.runs.models import RunSnapshot
from resume_tailor_harness.api.runs.notify import StreamNotifier
from resume_tailor_harness.api.schemas.runs import RunOut


class _RunSource(Protocol):
    """The subset of ``RunManager`` that ``run_events`` needs.

    A structural type rather than ``RunManager`` itself so the perf test's
    duck-typed manager double satisfies it without inheriting from the real
    class.
    """

    def get(self, run_id: str) -> RunSnapshot | None: ...
    def notifier(self, run_id: str) -> StreamNotifier: ...


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
        announced_at=snapshot.announced_at,
    )


async def run_events(
    mgr: _RunSource, run_id: str, *, poll_interval: float = 0.5
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
    wakeup = mgr.notifier(run_id)
    event = wakeup.subscribe()
    try:
        last: str | None = None
        while True:
            # Clear before reading, so a write that lands during the read is
            # still seen as a pending wakeup rather than being swallowed.
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
            try:
                await asyncio.wait_for(event.wait(), timeout=poll_interval)
            except (TimeoutError, asyncio.TimeoutError):
                pass
    finally:
        wakeup.unsubscribe(event)
