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
    resp = client.put(
        "/api/config/search",
        json={
            "keywords": ["python"],
            "titles": ["ML Engineer"],
            "locations": ["Remote"],
            "remotePolicy": "remote_only",
            "sponsorshipRequired": True,
        },
    )
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


def test_review_structural_knobs_round_trip(client):
    body = client.get("/api/config/review").json()
    assert body["mergedAdvisory"] is False
    assert body["tailorTier"] == "premium"
    assert body["reviserTier"] == "premium"
    response = client.put(
        "/api/config/review",
        json={
            **body,
            "mergedAdvisory": True,
            "tailorTier": "mid",
            "reviserTier": "cheap",
        },
    )
    assert response.status_code == 200
    saved = client.get("/api/config/review").json()
    assert saved["mergedAdvisory"] is True
    assert saved["tailorTier"] == "mid"
    assert saved["reviserTier"] == "cheap"


def test_review_provenance_retry_budget_survives_unrelated_saves(client):
    """A save that only touches other knobs must not silently reset this one."""
    body = client.get("/api/config/review").json()
    assert body["provenanceRetryBudget"] == 1  # ReviewConfig's own default

    put = client.put(
        "/api/config/review",
        json={**body, "provenanceRetryBudget": 0},
    )
    assert put.status_code == 200
    assert put.json()["provenanceRetryBudget"] == 0

    # Saving an unrelated knob afterward must not resurrect the old default.
    body = client.get("/api/config/review").json()
    response = client.put(
        "/api/config/review",
        json={**body, "mergedAdvisory": True},
    )
    assert response.status_code == 200
    saved = client.get("/api/config/review").json()
    assert saved["provenanceRetryBudget"] == 0
    assert saved["mergedAdvisory"] is True


def test_profile_repo_filters_round_trip_and_limit_is_bounded(client):
    response = client.put(
        "/api/config/profile",
        json={
            "githubUsername": "ada",
            "githubRepoAllow": ["important-fork"],
            "githubRepoDeny": ["noise"],
            "githubRepoLimit": 5,
        },
    )
    assert response.status_code == 200, response.text
    assert client.get("/api/config/profile").json() == {
        "githubUsername": "ada",
        "githubRepoAllow": ["important-fork"],
        "githubRepoDeny": ["noise"],
        "githubRepoLimit": 5,
    }
    assert (
        client.put("/api/config/profile", json={"githubRepoLimit": 0}).status_code
        == 422
    )


def test_render_contract_uses_template_id_only(client):
    assert client.get("/api/config/render").json() == {
        "template": "classic",
        "fitOnePage": True,
    }


def test_render_config_rejects_missing_and_path_like_templates(client):
    for template in ("custom:ghost", "custom:../secret"):
        response = client.put(
            "/api/config/render",
            json={"template": template, "fitOnePage": True},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "template_not_found"


def test_render_config_round_trip(client):
    response = client.put(
        "/api/config/render",
        json={"template": "classic", "fitOnePage": False},
    )
    assert response.status_code == 200
    assert client.get("/api/config/render").json()["fitOnePage"] is False
