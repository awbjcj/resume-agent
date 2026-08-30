from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from resume_agent.api.app import create_app


@pytest.fixture()
def client(tmp_path):
    app = create_app(
        db_url="sqlite://",
        config_dir=tmp_path / "config",
        env_path=tmp_path / ".env",
        data_dir=tmp_path / "data",
    )
    with TestClient(app) as test_client:
        yield test_client


def test_saved_board_view_crud_and_duplicate_conflict(client):
    created = client.post(
        "/api/board-views",
        json={
            "board": "shortlist",
            "name": " Strong remote roles ",
            "queryString": "remote=remote&fitMin=80",
        },
    )
    assert created.status_code == 201
    row = created.json()
    assert row["name"] == "Strong remote roles"
    assert row["queryString"] == "remote=remote&fitMin=80"

    duplicate = client.post(
        "/api/board-views",
        json={"board": "shortlist", "name": "Strong remote roles"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "VIEW_NAME_CONFLICT"

    other_board = client.post(
        "/api/board-views",
        json={"board": "pipeline", "name": "Strong remote roles"},
    )
    assert other_board.status_code == 201

    listed = client.get("/api/board-views", params={"board": "shortlist"})
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [row["id"]]

    updated = client.patch(
        f'/api/board-views/{row["id"]}',
        json={"name": "Top remote", "queryString": "fitMin=90"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Top remote"
    assert updated.json()["queryString"] == "fitMin=90"

    deleted = client.delete(f'/api/board-views/{row["id"]}')
    assert deleted.status_code == 204
    assert client.get("/api/board-views", params={"board": "shortlist"}).json() == []


def test_saved_board_view_rejects_unknown_board(client):
    response = client.post(
        "/api/board-views",
        json={"board": "unknown", "name": "Nope"},
    )
    assert response.status_code == 422


def test_saved_board_view_constraint_race_returns_conflict(client, monkeypatch):
    def fail_commit(_session):
        raise IntegrityError("INSERT INTO saved_board_view", {}, Exception("unique"))

    monkeypatch.setattr(Session, "commit", fail_commit)
    response = client.post(
        "/api/board-views",
        json={"board": "shortlist", "name": "Concurrent view"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "VIEW_NAME_CONFLICT"
