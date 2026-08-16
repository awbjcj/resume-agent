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
            "remotePolicy": ["remote", "hybrid"],
            "sponsorshipRequired": True,
        },
    )
    assert resp.status_code == 200
    body = client.get("/api/config/search").json()
    assert body["keywords"] == ["python"]
    assert body["remotePolicy"] == ["remote", "hybrid"]


def test_put_search_coerces_legacy_bare_string_remote_policy(client, tmp_path):
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "search.yaml").write_text(
        "remote_policy: remote\n", encoding="utf-8"
    )
    assert client.get("/api/config/search").json()["remotePolicy"] == ["remote"]


def test_normalize_locations(client):
    resp = client.post(
        "/api/config/search/normalize-locations",
        json={"raw": ["Austin, tex.", "Remote", "nyc"]},
    )
    assert resp.status_code == 200
    assert resp.json()["normalized"] == ["Austin, TX", "Remote", "New York, NY"]


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


def test_review_length_budget_exposes_depth_controls_on_the_wire(client):
    """The API carries the complete runtime budget, even without a settings UI."""
    body = client.get("/api/config/review").json()
    response = client.put(
        "/api/config/review",
        json={
            **body,
            "lengthBudget": {
                "pageTarget": 2,
                "maxExperiences": 5,
                "maxProjects": 4,
                "maxEvidenceOwners": 8,
                "minBulletsPerRole": 5,
                "maxBulletsPerRole": 7,
                "minBulletsPerProject": 4,
                "maxBulletsPerProject": 6,
                "targetTotalBullets": 40,
                "minAspectsPerOwner": 3,
                "targetSkills": 40,
                "maxSkillsPerCategory": 12,
            },
        },
    )
    assert response.status_code == 200, response.text
    budget = response.json()["lengthBudget"]
    assert budget["pageTarget"] == 2
    assert budget["minBulletsPerRole"] == 5
    assert budget["minBulletsPerProject"] == 4
    assert budget["minAspectsPerOwner"] == 3


def test_review_length_budget_accepts_a_legacy_cap_only_payload(client):
    body = client.get("/api/config/review").json()
    response = client.put(
        "/api/config/review",
        json={
            **body,
            "lengthBudget": {
                "maxExperiences": 1,
                "maxProjects": 1,
                "maxEvidenceOwners": 2,
                "maxBulletsPerRole": 2,
                "maxBulletsPerProject": 3,
                "targetTotalBullets": 3,
                "targetSkills": 40,
                "maxSkillsPerCategory": 12,
            },
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["lengthBudget"]["minBulletsPerRole"] == 2
    assert response.json()["lengthBudget"]["minBulletsPerProject"] == 3


def test_review_deep_is_a_separate_document_from_review(client):
    """The deep roster is its own file — saving one must not touch the other."""
    fast = client.get("/api/config/review").json()
    deep = client.get("/api/config/review-deep").json()

    response = client.put(
        "/api/config/review-deep",
        json={**deep, "evidencePortfolioEnabled": False, "mergedAdvisory": True},
    )
    assert response.status_code == 200
    assert client.get("/api/config/review-deep").json()["mergedAdvisory"] is True
    # review.yaml (fast roster) is untouched by the review-deep PUT.
    assert client.get("/api/config/review").json() == fast


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
