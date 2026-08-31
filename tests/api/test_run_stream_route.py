import asyncio
import json
from concurrent.futures import Executor, Future
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from resume_tailor_harness.api.app import create_app
from resume_tailor_harness.api.runs.conversation import with_conversation_stream
from resume_tailor_harness.api.runs.manager import RunManager
from resume_tailor_harness.sessions.stream import Completed, RunStreamSink, TextDelta


class InlineExecutor(Executor):
    def submit(self, fn, /, *args, **kwargs):
        future: Future = Future()
        future.set_result(fn(*args, **kwargs))
        return future


def _rows(response) -> list[dict]:
    return [
        json.loads(line[len("data:") :].strip())
        for line in response.iter_lines()
        if line.startswith("data:")
    ]


def test_stream_route_replays_from_offset_and_closes_on_terminal(tmp_path):
    app = create_app(
        db_url="sqlite://", run_executor=InlineExecutor(), runs_root=tmp_path
    )
    with TestClient(app) as client:
        run_id = app.state.run_manager.create("profileCoachMessage")
        sink = RunStreamSink(app.state.run_manager.stream_path(run_id), flush_chars=1)
        sink.emit(TextDelta("one"))
        sink.emit(TextDelta("two"))
        sink.emit(Completed())
        sink.close()

        with client.stream("GET", f"/api/runs/{run_id}/stream?offset=1") as response:
            assert response.status_code == 200
            rows = _rows(response)

    assert [row["i"] for row in rows] == [1, 2]
    assert rows[-1]["t"] == "completed"


def test_stream_route_rejects_negative_offset(tmp_path):
    app = create_app(
        db_url="sqlite://", run_executor=InlineExecutor(), runs_root=tmp_path
    )
    with TestClient(app) as client:
        run_id = app.state.run_manager.create("profileCoachMessage")
        response = client.get(f"/api/runs/{run_id}/stream?offset=-1")
    assert response.status_code == 422


def test_stream_route_404s_for_missing_run(tmp_path):
    app = create_app(
        db_url="sqlite://", run_executor=InlineExecutor(), runs_root=tmp_path
    )
    with TestClient(app) as client:
        response = client.get("/api/runs/missing/stream")
    assert response.status_code == 404


def test_terminal_run_fallback_preserves_error_truth(tmp_path):
    from resume_tailor_harness.api.runs.stream_sse import stream_events

    class Manager:
        def stream_path(self, run_id):
            return tmp_path / f"{run_id}.stream.ndjson"

        def get(self, run_id):
            return SimpleNamespace(
                state="error", error="provider failed", error_code="PROVIDER_ERROR"
            )

    async def collect():
        return [
            event
            async for event in stream_events(
                Manager(), "run", poll_interval=0, grace_polls=1
            )
        ]

    events = asyncio.run(collect())
    payload = json.loads(events[-1]["data"])
    assert payload == {
        "i": 0,
        "t": "failed",
        "v": {"message": "provider failed", "code": "PROVIDER_ERROR"},
    }


def test_conversation_wrapper_closes_stream_handle_when_work_raises(tmp_path):
    manager = RunManager(root=tmp_path, executor=InlineExecutor())
    run_id = manager.create("profileCoachMessage")

    def fail(_reporter, sink):
        sink.emit(TextDelta("partial"))
        raise RuntimeError("formatter failed")

    wrapped = with_conversation_stream(manager, fail)
    with pytest.raises(RuntimeError, match="formatter failed"):
        wrapped(SimpleNamespace(run_id=run_id))
    manager.stream_path(run_id).unlink()
