import pytest
from fastapi.testclient import TestClient

import resume_agent.api.routers.match_gap as match_gap_router
import resume_agent.api.routers.taxonomy as taxonomy_router
import resume_agent.profile.effective as effective_module
from resume_agent.api.app import create_app
from resume_agent.db import get_session
from resume_agent.taxonomy.clusters import ClusterMap, save_cluster_map
from resume_agent.tracking.repository import save_job
from resume_agent.tracking.tables import Job, JobStatus


@pytest.fixture()
def client(tmp_path, monkeypatch):
    corrections_path = tmp_path / "taxonomy_corrections.json"
    cluster_path = tmp_path / "cluster_map.json"
    facts_path = tmp_path / "facts.json"
    save_cluster_map(
        ClusterMap(
            aliases={
                "python": "python",
                "javascript": "javascript",
                "js": "javascript",
            },
            domain_of={"python": "scripting", "javascript": "web"},
            domain_label={"scripting": "Scripting", "web": "Web"},
            category_of={"scripting": "languages", "web": "frontend-web"},
        ),
        cluster_path,
    )
    monkeypatch.setattr(
        taxonomy_router,
        "_paths",
        lambda: (str(corrections_path), str(cluster_path)),
    )
    monkeypatch.setattr(match_gap_router, "_CLUSTER_PATH", str(cluster_path))
    monkeypatch.setattr(match_gap_router, "_FACTS_PATH", str(facts_path))
    monkeypatch.setattr(
        effective_module, "corrections_file_path", lambda: str(corrections_path)
    )
    monkeypatch.setattr(
        match_gap_router, "corrections_file_path", lambda: str(corrections_path)
    )
    app = create_app(db_url="sqlite://", data_dir=tmp_path / "data")
    with TestClient(app) as test_client:
        with get_session(app.state.engine) as session:
            save_job(
                session,
                Job(
                    source="manual",
                    status=JobStatus.shortlisted.value,
                    criteria_json={"must_have_skills": ["Python", "JavaScript", "JS"]},
                ),
            )
        yield test_client


def test_move_skill_to_new_domain_returns_updated_map(client):
    response = client.put(
        "/api/taxonomy/skills/python/domain",
        json={"newDomain": {"label": "Backend Languages", "category": "backend-apis"}},
    )
    assert response.status_code == 200
    payload = response.json()
    assert (
        next(s for s in payload["skills"] if s["key"] == "python")["domainId"]
        == "backend-languages"
    )


def test_move_unknown_domain_is_404_envelope(client):
    response = client.put(
        "/api/taxonomy/skills/python/domain", json={"domainId": "ghost"}
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "UNKNOWN_DOMAIN"


def test_bad_category_is_400_envelope(client):
    response = client.put(
        "/api/taxonomy/skills/python/domain",
        json={"newDomain": {"label": "X", "category": "bad"}},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "UNKNOWN_CATEGORY"


def test_remove_then_readd_skill(client):
    assert client.delete("/api/taxonomy/skills/python").status_code == 200
    assert all(
        s["key"] != "python" for s in client.get("/api/match-gap").json()["skills"]
    )
    response = client.post(
        "/api/taxonomy/skills",
        json={"token": "python", "domainId": "scripting"},
    )
    assert response.status_code == 200
    assert any(s["key"] == "python" for s in response.json()["skills"])


def test_compound_domain_patch_and_merge(client):
    patched = client.patch(
        "/api/taxonomy/domains/web",
        json={"label": "Frontend", "category": "tools-platforms"},
    )
    assert patched.status_code == 200
    domain = next(item for item in patched.json()["domains"] if item["id"] == "web")
    assert (domain["label"], domain["category"]) == ("Frontend", "tools-platforms")

    merged = client.post("/api/taxonomy/domains/web/merge", json={"into": "scripting"})
    assert merged.status_code == 200
    assert all(item["id"] != "web" for item in merged.json()["domains"])


def test_alias_unknown_skill_and_cycle_use_stable_envelopes(client):
    unknown = client.post(
        "/api/taxonomy/aliases", json={"token": "ghost", "canonical": "python"}
    )
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "UNKNOWN_SKILL"

    assert (
        client.post(
            "/api/taxonomy/aliases", json={"token": "js", "canonical": "javascript"}
        ).status_code
        == 200
    )
    cycle = client.post(
        "/api/taxonomy/aliases", json={"token": "javascript", "canonical": "js"}
    )
    assert cycle.status_code == 400
    assert cycle.json()["error"]["code"] == "ALIAS_CYCLE"


def test_empty_token_is_400_invalid_skill_token(client):
    response = client.post(
        "/api/taxonomy/aliases", json={"token": "   ", "canonical": "python"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_SKILL_TOKEN"
