"""The run acknowledgement endpoint.

Ack is how a completion stops being announced again on the next reconnect. It is
deliberately forgiving: the client is reporting what it displayed, and a batch
that has gone partly stale is normal, so unusable ids are skipped rather than
failing the whole request.
"""

from concurrent.futures import Executor, Future

from fastapi.testclient import TestClient

from resume_agent.api.app import create_app


class InlineExecutor(Executor):
    def submit(self, fn, /, *args, **kwargs):
        future: Future = Future()
        future.set_result(fn(*args, **kwargs))
        return future


def _app(tmp_path):
    return create_app(
        db_url="sqlite://", run_executor=InlineExecutor(), runs_root=tmp_path
    )


def test_ack_stamps_terminal_runs_and_removes_them_from_the_listing(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        run_id = app.state.run_manager.submit("tailor", lambda reporter: {"ok": True})

        listed = client.get("/api/runs").json()["data"]
        assert [item["runId"] for item in listed] == [run_id]
        assert listed[0]["announcedAt"] is None

        response = client.post("/api/runs/ack", json={"runIds": [run_id]})
        assert response.status_code == 200
        assert response.json() == {"acknowledged": 1}

        assert client.get("/api/runs").json()["data"] == []
        assert client.get(f"/api/runs/{run_id}").json()["announcedAt"] is not None


def test_ack_is_idempotent_and_skips_unusable_ids(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        run_id = app.state.run_manager.submit("tailor", lambda reporter: {"ok": True})
        pending = app.state.run_manager.create("tailor")

        first = client.post("/api/runs/ack", json={"runIds": [run_id]})
        assert first.json() == {"acknowledged": 1}

        second = client.post(
            "/api/runs/ack", json={"runIds": [run_id, pending, "no-such-run"]}
        )
        assert second.status_code == 200
        assert second.json() == {"acknowledged": 0}


def test_ack_accepts_an_empty_list(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post("/api/runs/ack", json={"runIds": []})
        assert response.status_code == 200
        assert response.json() == {"acknowledged": 0}
