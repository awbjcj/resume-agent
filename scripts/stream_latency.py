"""Opt-in live latency probe for an existing Profile Coach session."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time

import httpx


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[round((len(ordered) - 1) * fraction)]


async def probe(base_url: str, session_id: str, message: str) -> None:
    token = os.environ.get("RESUME_AGENT_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    started = time.perf_counter()
    async with httpx.AsyncClient(base_url=base_url, headers=headers, timeout=120) as client:
        launch = await client.post(
            f"/api/profile/coach/sessions/{session_id}/messages",
            json={"message": message},
        )
        launch.raise_for_status()
        run_id = launch.json()["runId"]
        text_times: list[float] = []
        event_count = 0
        payload_bytes = 0
        settled_at: float | None = None
        completed_at: float | None = None
        async with client.stream("GET", f"/api/runs/{run_id}/stream") as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                raw = line.removeprefix("data:").strip()
                payload_bytes += len(raw.encode("utf-8")) + 1
                event_count += 1
                event = json.loads(raw)
                now = time.perf_counter()
                if event.get("t") == "text":
                    text_times.append(now)
                elif event.get("t") == "settled":
                    settled_at = now
                elif event.get("t") in {"completed", "failed"}:
                    completed_at = now
                    break

    gaps = [right - left for left, right in zip(text_times, text_times[1:])]
    ttft = (text_times[0] - started) if text_times else 0.0
    post_prose = (
        completed_at - settled_at
        if settled_at is not None and completed_at is not None
        else 0.0
    )
    print(f"run: {run_id}")
    print(f"TTFT: {ttft * 1000:.1f} ms")
    print(f"inter-chunk p50: {statistics.median(gaps) * 1000:.1f} ms")
    print(f"inter-chunk p95: {_percentile(gaps, 0.95) * 1000:.1f} ms")
    print(f"events: {event_count}")
    print(f"received event bytes: {payload_bytes}")
    print(f"prose settled to run completed: {post_prose * 1000:.1f} ms")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("session_id")
    parser.add_argument("message")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    asyncio.run(probe(args.base_url.rstrip("/"), args.session_id, args.message))


if __name__ == "__main__":
    main()
