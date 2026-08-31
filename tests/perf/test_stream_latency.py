"""Deterministic structural guards for the conversational stream hot path."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from resume_tailor_harness.api.runs import stream_sse
from resume_tailor_harness.api.runs.notify import StreamNotifier
from resume_tailor_harness.sessions.stream import (
    Completed,
    RunStreamSink,
    TextDelta,
    read_stream,
)
from resume_tailor_harness.sessions.turns import ProseEmitter


class _Clock:
    now = 0.0

    def __call__(self) -> float:
        return self.now


class _Manager:
    def __init__(self, path) -> None:
        self.path = path
        self.wakeup = StreamNotifier()

    def stream_path(self, _run_id):
        return self.path

    def notifier(self, _run_id):
        return self.wakeup

    def get(self, _run_id):
        return SimpleNamespace(state="running")


class _Recorder:
    def __init__(self) -> None:
        self.text = ""

    def emit(self, event) -> None:
        if isinstance(event, TextDelta):
            self.text += event.text

    def close(self) -> None:
        pass


def _batch_metrics(tmp_path, interval: float, chars: int) -> tuple[int, int]:
    clock = _Clock()
    path = tmp_path / f"{interval}-{chars}.ndjson"
    sink = RunStreamSink(path, flush_interval=interval, flush_chars=chars, clock=clock)
    for _ in range(120):
        sink.emit(TextDelta("x" * 15))
        clock.now += 0.01
    sink.close()
    return len(list(read_stream(path))), path.stat().st_size


def test_notifier_wakes_reader_without_poll_sleep(tmp_path, monkeypatch):
    path = tmp_path / "run.ndjson"
    manager = _Manager(path)
    sink = RunStreamSink(path, flush_chars=1, on_append=manager.wakeup.notify)
    waits: list[float] = []

    async def controlled_wait(event: asyncio.Event, timeout: float) -> None:
        waits.append(timeout)
        sink.emit(TextDelta("visible"))
        sink.emit(Completed())
        await event.wait()

    monkeypatch.setattr(stream_sse, "_wait_for_append", controlled_wait)

    async def collect():
        return [event async for event in stream_sse.stream_events(manager, "run")]

    rows = [json.loads(event["data"]) for event in asyncio.run(collect())]
    sink.close()
    assert waits == [0.25]
    assert [row["t"] for row in rows] == ["text", "completed"]


def test_timeout_fallback_delivers_when_notification_is_dropped(tmp_path, monkeypatch):
    path = tmp_path / "run.ndjson"
    manager = _Manager(path)
    sink = RunStreamSink(path, flush_chars=1)

    async def dropped_notification(_event: asyncio.Event, _timeout: float) -> None:
        sink.emit(TextDelta("recovered"))
        sink.emit(Completed())

    monkeypatch.setattr(stream_sse, "_wait_for_append", dropped_notification)

    async def collect():
        return [event async for event in stream_sse.stream_events(manager, "run")]

    rows = [json.loads(event["data"]) for event in asyncio.run(collect())]
    sink.close()
    assert [row["t"] for row in rows] == ["text", "completed"]


def test_boundary_free_prose_has_zero_character_lag():
    recorder = _Recorder()
    emitter = ProseEmitter(recorder)
    emitter.feed("A complete ordinary sentence.")
    assert recorder.text == "A complete ordinary sentence."


def test_retuned_batch_window_stays_within_twice_the_legacy_event_count(tmp_path):
    legacy_events, legacy_bytes = _batch_metrics(tmp_path, 0.08, 240)
    selected_events, selected_bytes = _batch_metrics(tmp_path, 0.04, 120)
    assert legacy_events == 15
    assert selected_events == 30
    assert selected_events <= legacy_events * 2
    assert selected_bytes > legacy_bytes
