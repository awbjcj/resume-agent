"""Tail a conversational run's append-only event log as SSE."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from resume_agent.sessions.stream import TERMINAL_TAGS, StreamTail

_GRACE_POLLS = 4


async def _wait_for_append(event: asyncio.Event, timeout: float) -> None:
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
    except TimeoutError:
        pass


async def stream_events(
    mgr,
    run_id: str,
    offset: int = 0,
    *,
    poll_interval: float = 0.25,
    grace_polls: int = _GRACE_POLLS,
) -> AsyncIterator[dict]:
    """Yield complete events at or after ``offset`` until a terminal event."""
    path = mgr.stream_path(run_id)
    cursor = offset
    terminal_polls = 0
    tail = StreamTail(path)
    notifier_factory = getattr(mgr, "notifier", None)
    notifier = notifier_factory(run_id) if notifier_factory is not None else None
    wakeup = notifier.subscribe() if notifier is not None else None
    try:
        while True:
            if wakeup is not None:
                wakeup.clear()
            for index, tag, payload in tail.read(cursor):
                cursor = index + 1
                yield {
                    "data": json.dumps(
                        {"i": index, "t": tag, "v": payload},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                }
                if tag in TERMINAL_TAGS:
                    return

            snapshot = mgr.get(run_id)
            state = getattr(snapshot, "state", None)
            state = getattr(state, "value", state)
            terminal = state in {"done", "error", "cancelled"}
            if terminal:
                terminal_polls += 1
                if terminal_polls >= max(grace_polls, 1):
                    if state == "done":
                        tag = "completed"
                        payload = {}
                    else:
                        tag = "failed"
                        payload = {
                            "message": getattr(snapshot, "error", None)
                            or (
                                "Generation stopped."
                                if state == "cancelled"
                                else "Run failed."
                            ),
                            "code": getattr(snapshot, "error_code", None)
                            or ("CANCELLED" if state == "cancelled" else "RUN_ERROR"),
                        }
                    yield {
                        "data": json.dumps(
                            {"i": cursor, "t": tag, "v": payload},
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                    }
                    return
            else:
                terminal_polls = 0

            timeout = min(poll_interval, 0.05) if terminal else poll_interval
            if wakeup is None:
                await asyncio.sleep(timeout)
            else:
                await _wait_for_append(wakeup, timeout)
    finally:
        if notifier is not None and wakeup is not None:
            notifier.unsubscribe(wakeup)
            release = getattr(mgr, "release_notifier", None)
            if release is not None:
                release(run_id, notifier)
