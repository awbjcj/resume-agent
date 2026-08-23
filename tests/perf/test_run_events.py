"""Run-progress SSE is notifier-driven, with the poll as the fallback.

The stream used to sleep out a fixed 500 ms between reads *and* do the file
read inline on the event loop. The first made a fast run's terminal event
arrive up to 500 ms late; the second let one slow volume stall the API loop for
every connected client.
"""

from __future__ import annotations

import asyncio
import json
import time
from types import SimpleNamespace

from resume_agent.api.runs.notify import StreamNotifier
from resume_agent.api.runs.sse import run_events

POLL = 0.5


class _Manager:
    """A run whose state flips once, announced through the notifier."""

    def __init__(self, *, announce: bool = True, read_delay: float = 0.0) -> None:
        self.wakeup = StreamNotifier()
        self.state = "running"
        self.announce = announce
        self.read_delay = read_delay
        self.reads = 0

    def notifier(self, _run_id: str) -> StreamNotifier:
        return self.wakeup

    def get(self, run_id: str):
        self.reads += 1
        if self.read_delay:
            time.sleep(self.read_delay)
        return SimpleNamespace(
            run_id=run_id,
            kind="pull",
            state=self.state,
            label="Working",
            percent=100 if self.state == "done" else 10,
            current=1,
            total=1,
            eta_text=None,
            result=None,
            error=None,
            error_code=None,
            meta=None,
            announced_at=None,
        )

    def finish(self) -> None:
        self.state = "done"
        if self.announce:
            self.wakeup.notify()


async def _drain(mgr, *, after: float) -> tuple[list[dict], float]:
    started = time.monotonic()

    async def finish_soon() -> None:
        await asyncio.sleep(after)
        mgr.finish()

    task = asyncio.create_task(finish_soon())
    events = [json.loads(event["data"]) async for event in run_events(mgr, "r1", poll_interval=POLL)]
    await task
    return events, time.monotonic() - started


def test_a_fast_run_delivers_its_terminal_event_without_waiting_out_the_poll():
    mgr = _Manager()

    events, elapsed = asyncio.run(_drain(mgr, after=0.05))

    assert events[-1]["state"] == "done"
    assert elapsed < POLL / 2, f"{elapsed:.3f}s waited out the poll interval"


def test_a_notifier_that_never_fires_still_terminates_via_the_fallback():
    """The notifier is a low-latency wakeup; it never owns stream truth."""
    mgr = _Manager(announce=False)

    events, elapsed = asyncio.run(_drain(mgr, after=0.05))

    assert events[-1]["state"] == "done"
    assert elapsed >= POLL / 2  # it did fall back to the poll


def test_the_snapshot_read_does_not_run_on_the_event_loop():
    """A slow volume must not stall the loop every connected client shares."""
    mgr = _Manager(read_delay=0.1)
    ticks = 0

    async def spin() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.005)
            ticks += 1

    async def drive() -> None:
        spinner = asyncio.create_task(spin())
        await _drain(mgr, after=0.05)
        spinner.cancel()

    asyncio.run(drive())

    # An inline 100 ms read would have blocked the loop through the whole run,
    # leaving the co-running task almost no chance to tick.
    assert ticks >= 5, ticks
