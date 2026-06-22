import json
from concurrent.futures import Executor, Future

from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.api.routers import runs as runs_router


class InlineExecutor(Executor):
    def submit(self, fn, /, *args, **kwargs):
        fut: Future = Future()
        fut.set_result(fn(*args, **kwargs))
        return fut


def test_sse_stream_emits_terminal_event(monkeypatch, tmp_path):
    def fake_discover_jobs(session, *, reporter=None, **kw):
        reporter.begin(1, "scoring")  # type: ignore[attr-defined]
        reporter.step(1)  # type: ignore[attr-defined]
        return {"shortlisted": 1}

    monkeypatch.setattr(runs_router, "discover_jobs", fake_discover_jobs)
    client = TestClient(
        create_app(db_url="sqlite://", run_executor=InlineExecutor(), runs_root=tmp_path)
    )
    with client:
        run_id = client.post("/api/discover", json={}).json()["runId"]
        # InlineExecutor means the run is already terminal; the stream should
        # emit at least one event ending in a done state, then close.
        with client.stream("GET", f"/api/runs/{run_id}/events") as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers["content-type"]
            events = []
            for line in resp.iter_lines():
                if line.startswith("data:"):
                    events.append(json.loads(line[len("data:"):].strip()))
                    if events[-1]["state"] in ("done", "error"):
                        break
    assert events[-1]["state"] == "done"
    assert events[-1]["percent"] == 100
