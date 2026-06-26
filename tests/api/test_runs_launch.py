from concurrent.futures import Executor, Future

from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.api.routers import runs as runs_router


class InlineExecutor(Executor):
    def submit(self, fn, /, *args, **kwargs):
        fut: Future = Future()
        try:
            fut.set_result(fn(*args, **kwargs))
        except Exception as exc:  # noqa: BLE001
            fut.set_exception(exc)
        return fut


def _client(tmp_path):
    return TestClient(
        create_app(db_url="sqlite://", run_executor=InlineExecutor(), runs_root=tmp_path)
    )


def test_discover_launch_returns_run(monkeypatch, tmp_path):
    # Fake the service so no LLM/network runs; assert the run wiring works.
    def fake_discover_jobs(session, *, reporter=None, **kw):
        reporter.begin(1, "x")  # type: ignore[attr-defined]
        reporter.step(1)  # type: ignore[attr-defined]
        return {"shortlisted": 2}

    monkeypatch.setattr(runs_router, "discover_jobs", fake_discover_jobs)
    client = _client(tmp_path)
    with client:
        resp = client.post("/api/discover", json={})
        assert resp.status_code == 202
        run_id = resp.json()["runId"]
        got = client.get(f"/api/runs/{run_id}").json()
    assert got["kind"] == "discover"
    assert got["state"] == "done"
    assert got["result"] == {"statusCounts": {"shortlisted": 2}}
    assert got["percent"] == 100


def test_get_unknown_run_404(tmp_path):
    client = _client(tmp_path)
    with client:
        assert client.get("/api/runs/deadbeef").status_code == 404


def test_tailor_launch_passes_params(monkeypatch, tmp_path):
    captured = {}

    def fake_tailor(session, *, job_ids=None, approved=False, reporter=None, **kw):
        captured["job_ids"] = job_ids
        captured["approved"] = approved
        captured["fail_on_partial"] = kw.get("fail_on_partial")
        reporter.begin(1, "x")  # type: ignore[attr-defined]
        reporter.step(1)  # type: ignore[attr-defined]
        return {}

    monkeypatch.setattr(runs_router, "tailor", fake_tailor)
    client = _client(tmp_path)
    with client:
        client.post("/api/tailor", json={"jobIds": [1, 2], "approved": False})
    assert captured["job_ids"] == [1, 2]
    assert captured["fail_on_partial"] is True


def test_reprocess_endpoint_launches_run(monkeypatch, tmp_path):
    def fake_reprocess_jobs(session, *, scopes, reporter=None, **kw):
        return {"shortlisted": 1}

    monkeypatch.setattr(runs_router, "reprocess_jobs", fake_reprocess_jobs)
    client = _client(tmp_path)
    with client:
        resp = client.post("/api/reprocess", json={"scopes": ["shortlisted"]})
    assert resp.status_code == 202
    assert resp.json()["kind"] == "reprocess"


def test_refresh_endpoint_launches_run(monkeypatch, tmp_path):
    from resume_agent.services.discovery import RefreshReport

    def fake_refresh_jobs(session, *, limit=None, reporter=None, **kw):
        return RefreshReport(pulled=0, totals={}, status_counts={}, failures={})

    monkeypatch.setattr(runs_router, "refresh_jobs", fake_refresh_jobs)
    client = _client(tmp_path)
    with client:
        resp = client.post("/api/refresh", json={"limit": None})
    assert resp.status_code == 202
    assert resp.json()["kind"] == "refresh"
