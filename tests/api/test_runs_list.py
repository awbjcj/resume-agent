"""Active-run list contract for browser rehydration."""

from fastapi.testclient import TestClient

from resume_agent.api.app import create_app


def test_list_runs_returns_paginated_active_snapshots(tmp_path):
    app = create_app(db_url="sqlite://", runs_root=tmp_path)
    with TestClient(app) as client:
        for kind in ("pull", "discover", "tailor"):
            app.state.run_manager.create(kind)
        expected = [snapshot.run_id for snapshot in app.state.run_manager.list_active()]

        response = client.get("/api/runs", params={"page": 1, "pageSize": 2})

    assert response.status_code == 200
    body = response.json()
    assert [item["runId"] for item in body["data"]] == expected[:2]
    assert body["pagination"] == {
        "page": 1,
        "pageSize": 2,
        "totalItems": 3,
        "totalPages": 2,
    }
    assert all(item["state"] == "pending" for item in body["data"])


def test_list_runs_rejects_invalid_page_size(tmp_path):
    app = create_app(db_url="sqlite://", runs_root=tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/runs", params={"pageSize": 0})

    assert response.status_code == 422


def test_list_runs_includes_failed_revision_for_durable_retry(tmp_path):
    app = create_app(
        db_url="sqlite://", runs_root=tmp_path, env_path=tmp_path / "missing.env"
    )
    with TestClient(app) as client:
        run_id = app.state.run_manager.create(
            "revise",
            meta={"versionId": 5, "jobId": 3, "instruction": "shorter"},
        )
        app.state.run_manager.reporter(run_id, "revise").done(error="provider failed")

        response = client.get("/api/runs")

    assert response.status_code == 200
    runs = response.json()["data"]
    assert len(runs) == 1
    assert runs[0]["runId"] == run_id
    assert runs[0]["kind"] == "revise"
    assert runs[0]["state"] == "error"
    assert runs[0]["error"] == "provider failed"
    assert runs[0]["meta"] == {
        "versionId": 5,
        "jobId": 3,
        "instruction": "shorter",
    }


def test_list_runs_only_rehydrates_the_latest_revision_attempt(tmp_path):
    app = create_app(
        db_url="sqlite://", runs_root=tmp_path, env_path=tmp_path / "missing.env"
    )
    with TestClient(app) as client:
        failed_id = app.state.run_manager.create(
            "revise", meta={"versionId": 5, "jobId": 3, "instruction": "shorter"}
        )
        app.state.run_manager.reporter(failed_id, "revise").done(error="first failed")
        retry_id = app.state.run_manager.create(
            "revise", meta={"versionId": 5, "jobId": 3, "instruction": "shorter"}
        )

        active = client.get("/api/runs").json()["data"]
        app.state.run_manager.reporter(retry_id, "revise").done(result={"versionId": 6})
        completed = client.get("/api/runs").json()["data"]

    assert [run["runId"] for run in active] == [retry_id]
    # The succeeded retry is now rehydratable until acknowledged -- that is the
    # whole point of the announce window: a completion the client never saw must
    # still be recoverable. The superseded first attempt stays hidden, so the
    # retry UI is never offered a failure the user has already moved past.
    assert [run["runId"] for run in completed] == [retry_id]
    assert failed_id not in {run["runId"] for run in completed}
