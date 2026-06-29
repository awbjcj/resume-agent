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
