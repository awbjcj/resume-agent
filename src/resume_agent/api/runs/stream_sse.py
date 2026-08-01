"""Tail a conversational run's append-only event log as SSE."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from resume_agent.sessions.stream import TERMINAL_TAGS, read_stream

_GRACE_POLLS = 4


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
    while True:
        for index, tag, payload in read_stream(path, cursor):
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
        if state in {"done", "error", "cancelled"}:
            terminal_polls += 1
            if terminal_polls >= max(grace_polls, 1):
                if state == "done":
                    tag = "completed"
                    payload = {}
                else:
                    tag = "failed"
                    payload = {
                        "message": getattr(snapshot, "error", None)
                        or ("Generation stopped." if state == "cancelled" else "Run failed."),
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
        await asyncio.sleep(poll_interval)
