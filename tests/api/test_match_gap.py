from fastapi.testclient import TestClient

import resume_agent.api.routers.match_gap as router_mod
from resume_agent.api.app import create_app
from resume_agent.db import get_session
from resume_agent.taxonomy.clusters import ClusterMap, save_cluster_map
from resume_agent.tracking.repository import save_job
from resume_agent.tracking.tables import Job, JobStatus


def _client():
    return TestClient(create_app(db_url="sqlite://"))


def test_match_gap_empty_db_returns_empty_graph():
    client = _client()
    with client:
        resp = client.get("/api/match-gap")

    assert resp.status_code == 200
    body = resp.json()
    assert body["targetTotal"] == 0
    assert body["jobs"] == []
    assert body["skills"] == []
    assert body["edges"] == []
    assert body["themes"] == []
    assert body["clustersStale"] is False


def test_match_gap_projects_jobs_skills_edges_and_themes(monkeypatch, tmp_path):
    cluster_path = tmp_path / "cluster_map.json"
    save_cluster_map(
        ClusterMap(
            aliases={"k8s": "kubernetes", "kubernetes": "kubernetes"},
            theme_of={"kubernetes": "infra"},
            theme_label={"infra": "Cloud / Infrastructure"},
        ),
        cluster_path,
    )
    monkeypatch.setattr(router_mod, "_CLUSTER_PATH", str(cluster_path))
    monkeypatch.setattr(router_mod, "_FACTS_PATH", str(tmp_path / "missing-facts.json"))

    app = create_app(db_url="sqlite://")
    with TestClient(app) as client:
        with get_session(app.state.engine) as session:
            save_job(
                session,
                Job(
                    source="manual",
                    company="Stripe",
                    title="Platform Engineer",
                    status=JobStatus.shortlisted.value,
                    criteria_json={
                        "must_have_skills": ["K8s"],
                        "nice_to_have_skills": ["Kubernetes"],
                        "seniority": "senior",
                    },
                ),
            )
        resp = client.get("/api/match-gap")

    assert resp.status_code == 200
    assert resp.json() == {
        "targetTotal": 1,
        "clustersStale": False,
        "jobs": [
            {
                "id": 1,
                "company": "Stripe",
                "title": "Platform Engineer",
                "seniority": "senior",
            }
        ],
        "skills": [{"skill": "K8s", "themeId": "infra", "covered": False}],
        "edges": [
            {"jobId": 1, "skill": "K8s", "source": "must"},
            {"jobId": 1, "skill": "K8s", "source": "nice"},
        ],
        "themes": [{"id": "infra", "label": "Cloud / Infrastructure"}],
    }
