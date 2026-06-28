from fastapi.testclient import TestClient

import resume_agent.api.routers.match_gap as router_mod
from resume_agent.api.app import create_app
from resume_agent.db import get_session
from resume_agent.models.profile import Contact, ProfileFacts
from resume_agent.services.suggestions import (
    resolve_suggestion_context,
    suggestion_fingerprint,
)
from resume_agent.taxonomy.clusters import ClusterMap, save_cluster_map
from resume_agent.tracking.match_gap import build_demand_graph
from resume_agent.tracking.repository import save_job
from resume_agent.tracking.tables import Job, JobStatus, SkillSuggestion


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
    assert body["suggestionStatuses"] == []
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
        "skills": [
            {
                "skill": "K8s",
                "themeId": "infra",
                "covered": False,
                "key": "kubernetes",
                "members": {"K8s": 1, "Kubernetes": 1},
                "must": 1,
                "nice": 1,
                "tech": 0,
                "jobCount": 1,
            }
        ],
        "edges": [
            {
                "jobId": 1,
                "skill": "K8s",
                "source": "must",
                "skillKey": "kubernetes",
            },
            {
                "jobId": 1,
                "skill": "K8s",
                "source": "nice",
                "skillKey": "kubernetes",
            },
        ],
        "themes": [
            {
                "id": "infra",
                "label": "Cloud / Infrastructure",
                "essentialScore": 5,
                "popularScore": 1,
                "jobCount": 1,
                "skillCount": 1,
                "gapCount": 1,
            }
        ],
        "suggestionStatuses": [],
    }


def test_match_gap_includes_canonical_persisted_suggestion_status(monkeypatch, tmp_path):
    cluster_path = tmp_path / "cluster_map.json"
    cluster_map = ClusterMap(
        aliases={"python": "python"},
        theme_of={"python": "backend"},
        theme_label={"backend": "Backend"},
    )
    save_cluster_map(cluster_map, cluster_path)
    monkeypatch.setattr(router_mod, "_CLUSTER_PATH", str(cluster_path))
    monkeypatch.setattr(router_mod, "_FACTS_PATH", str(tmp_path / "missing-facts.json"))
    app = create_app(db_url="sqlite://")

    with TestClient(app) as client:
        with get_session(app.state.engine) as session:
            save_job(
                session,
                Job(
                    source="manual",
                    company="Acme",
                    title="Backend Engineer",
                    status=JobStatus.shortlisted.value,
                    criteria_json={"must_have_skills": ["Python"]},
                ),
            )
            facts = ProfileFacts(contact=Contact(name=""))
            graph = build_demand_graph(session, facts, cluster_map)
            context = resolve_suggestion_context(graph, kind="skill", key="python")
            session.add(
                SkillSuggestion(
                    kind="skill",
                    key="python",
                    fingerprint=suggestion_fingerprint(context, set()),
                    payload_json={"bridge": "Bridge"},
                )
            )
            session.commit()

        response = client.get("/api/match-gap")

    status = response.json()["suggestionStatuses"][0]
    assert {key: status[key] for key in ("kind", "key", "state")} == {
        "kind": "skill",
        "key": "python",
        "state": "ready",
    }
    assert status["generatedAt"]
