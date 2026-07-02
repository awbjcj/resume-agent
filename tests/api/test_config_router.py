"""GET serves defaults/current file; PUT validates, persists, and echoes."""

import pytest
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    app = create_app(db_url="sqlite://", config_dir=tmp_path / "config")
    with TestClient(app) as c:
        yield c


def test_get_search_defaults(client):
    resp = client.get("/api/config/search")
    assert resp.status_code == 200
    body = resp.json()
    assert body["keywords"] == []
    assert body["sponsorshipRequired"] is False  # camelCase wire


def test_put_search_round_trip(client):
    resp = client.put("/api/config/search", json={
        "keywords": ["python"], "titles": ["ML Engineer"], "locations": ["Remote"],
        "remotePolicy": "remote_only", "sponsorshipRequired": True,
    })
    assert resp.status_code == 200
    assert client.get("/api/config/search").json()["keywords"] == ["python"]


def test_put_invalid_types_is_422(client):
    resp = client.put("/api/config/prune", json={"fitThreshold": "not-a-number"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


def test_style_guide_get_put(client):
    assert client.get("/api/config/style-guide").json() == {"content": ""}
    put = client.put("/api/config/style-guide", json={"content": "# Style"})
    assert put.status_code == 200
    assert client.get("/api/config/style-guide").json()["content"] == "# Style"


def test_review_reviewers_default_roster(client):
    body = client.get("/api/config/review").json()
    names = [r["name"] for r in body["reviewers"]]
    assert names[0] == "fact-check"
    assert body["reviewers"][0]["gate"] is True
