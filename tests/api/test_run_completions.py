from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from resume_agent.api.app import create_app
from resume_agent.services.run_completions import record_run_completion


@pytest.fixture()
def app_client(tmp_path):
    app = create_app(
        db_url="sqlite://",
        config_dir=tmp_path / "config",
        env_path=tmp_path / ".env",
        data_dir=tmp_path / "data",
    )
    with TestClient(app) as client:
        yield app, client


def test_run_completion_history_and_read_state(app_client):
    app, client = app_client
    with Session(app.state.engine) as session:
        record_run_completion(
            session,
            run_id="run-1",
            kind="discover",
            label="Discovery",
            status="succeeded",
            error=None,
            completed_at=datetime(2026, 8, 29, tzinfo=timezone.utc),
        )

    listed = client.get("/api/run-completions")
    assert listed.status_code == 200
    [row] = listed.json()
    assert row["runId"] == "run-1"
    assert row["readAt"] is None

    marked = client.post(f'/api/run-completions/{row["id"]}/read')
    assert marked.status_code == 200
    assert marked.json()["readAt"] is not None
    assert client.get(
        "/api/run-completions", params={"unread_only": True}
    ).json() == []


def test_completed_app_run_is_persisted_by_terminal_hook(app_client):
    app, client = app_client
    run_id = app.state.run_manager.submit("discover", lambda _reporter: {"ok": True})
    for future in list(app.state.run_manager._futures.values()):
        future.result(timeout=2)

    [row] = client.get("/api/run-completions").json()
    assert row["runId"] == run_id
    assert row["status"] == "succeeded"
