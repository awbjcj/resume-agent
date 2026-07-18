import time

from fastapi.testclient import TestClient

import resume_agent.api.routers.suggestions as router_module
import resume_agent.services.suggestion_runs as run_module
from resume_agent.api.app import create_app
from resume_agent.db import get_session
from resume_agent.github.repos import RepoMeta
from resume_agent.suggestions.agents import RepoRef, SuggestionDraft
from resume_agent.taxonomy.clusters import ClusterMap, save_cluster_map
from resume_agent.tracking.repository import save_job
from resume_agent.tracking.tables import Job, JobStatus


class _Result:
    def __init__(self, content):
        self.content = content


class _Agent:
    def __init__(self, content):
        self.content = content

    def run(self, _prompt):
        return _Result(self.content)


def _seed_job(engine, *, company="C", skills=None):
    with get_session(engine) as session:
        save_job(
            session,
            Job(
                source="manual",
                company=company,
                title="Platform Engineer",
                status=JobStatus.shortlisted.value,
                criteria_json={"must_have_skills": skills or ["Kubernetes", "Terraform"]},
            ),
        )


def _configure(monkeypatch, tmp_path):
    cluster_path = tmp_path / "cluster_map.json"
    save_cluster_map(
        ClusterMap(
            aliases={"kubernetes": "kubernetes", "terraform": "terraform"},
            domain_of={"kubernetes": "infra", "terraform": "infra"},
            domain_label={"infra": "Cloud / Infrastructure"},
        ),
        cluster_path,
    )
    monkeypatch.setattr(router_module, "_CLUSTER_PATH", str(cluster_path))
    monkeypatch.setattr(router_module, "_FACTS_PATH", str(tmp_path / "missing-facts.json"))


def _wait_for_run(client, run_id):
    for _ in range(50):
        record = client.get(f"/api/runs/{run_id}").json()
        if record["state"] in ("done", "error"):
            return record
        time.sleep(0.02)
    raise AssertionError(f"run {run_id} did not finish in time")


def test_get_returns_empty_envelope_for_valid_uncached_target(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    app = create_app(db_url="sqlite://", runs_root=tmp_path)
    with TestClient(app) as client:
        _seed_job(app.state.engine)
        response = client.get(
            "/api/suggestions",
            params={"kind": "skill", "key": "Kubernetes"},
        )

    assert response.status_code == 200
    assert response.json() == {"suggestion": None, "stale": False}


def test_unknown_targets_use_standard_not_found_envelope(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    app = create_app(db_url="sqlite://", runs_root=tmp_path)
    with TestClient(app) as client:
        _seed_job(app.state.engine)
        get_response = client.get(
            "/api/suggestions",
            params={"kind": "skill", "key": "Unknown"},
        )
        post_response = client.post(
            "/api/suggestions/generate",
            json={"kind": "domain", "key": "unknown"},
        )

    assert get_response.status_code == 404
    assert get_response.json()["error"]["code"] == "NOT_FOUND"
    assert post_response.status_code == 404
    assert post_response.json()["error"]["code"] == "NOT_FOUND"


def test_generate_rejects_browser_supplied_context(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    app = create_app(db_url="sqlite://", runs_root=tmp_path)
    with TestClient(app) as client:
        _seed_job(app.state.engine)
        response = client.post(
            "/api/suggestions/generate",
            json={
                "kind": "skill",
                "key": "Kubernetes",
                "members": ["Browser controlled"],
            },
        )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_generate_skill_then_get_cached_suggestion(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    draft = SuggestionDraft(
        repos=[RepoRef(name="foo/bar", url="https://github.com/foo/bar", why="Reference")],
        bridge="Bridge",
    )
    monkeypatch.setattr(
        run_module,
        "build_search_agent",
        lambda: _Agent("Research: https://github.com/foo/bar"),
    )
    monkeypatch.setattr(run_module, "build_formatter_agent", lambda: _Agent(draft))
    monkeypatch.setattr(
        run_module,
        "verify_repo",
        lambda owner, name, token="": RepoMeta(
            "foo/bar", "https://github.com/foo/bar", 5, "Repository"
        ),
    )

    app = create_app(db_url="sqlite://", runs_root=tmp_path)
    with TestClient(app) as client:
        _seed_job(app.state.engine)
        launched = client.post(
            "/api/suggestions/generate",
            json={"kind": "skill", "key": "Kubernetes"},
        )
        assert launched.status_code == 202
        record = _wait_for_run(client, launched.json()["runId"])
        cached = client.get(
            "/api/suggestions",
            params={"kind": "skill", "key": "Kubernetes"},
        )

    assert record["state"] == "done"
    assert cached.json()["suggestion"]["repos"][0]["stars"] == 5
    assert cached.json()["stale"] is False


def test_theme_cache_becomes_stale_when_demanding_jobs_change(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    monkeypatch.setattr(run_module, "build_search_agent", lambda: _Agent("Research"))
    monkeypatch.setattr(
        run_module,
        "build_formatter_agent",
        lambda: _Agent(SuggestionDraft(bridge="Theme bridge")),
    )

    app = create_app(db_url="sqlite://", runs_root=tmp_path)
    with TestClient(app) as client:
        _seed_job(app.state.engine)
        launched = client.post(
            "/api/suggestions/generate",
            json={"kind": "domain", "key": "infra"},
        )
        assert _wait_for_run(client, launched.json()["runId"])["state"] == "done"

        _seed_job(app.state.engine, company="D", skills=["Terraform"])
        cached = client.get(
            "/api/suggestions",
            params={"kind": "domain", "key": "infra"},
        )

    assert cached.json()["suggestion"]["key"] == "infra"
    assert cached.json()["stale"] is True


def test_suggestion_runs_dedupe_and_report_not_found_per_target(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    monkeypatch.setattr(run_module, "build_search_agent", lambda: _Agent("Research"))
    monkeypatch.setattr(
        run_module,
        "build_formatter_agent",
        lambda: _Agent(SuggestionDraft(bridge="Bridge")),
    )
    monkeypatch.setattr(run_module, "verify_repo", lambda *_args, **_kwargs: None)
    app = create_app(db_url="sqlite://", runs_root=tmp_path)

    with TestClient(app) as client:
        _seed_job(app.state.engine)
        response = client.post(
            "/api/suggestion-runs",
            json={
                "targets": [
                    {"kind": "skill", "key": "kubernetes"},
                    {"kind": "skill", "key": "kubernetes"},
                    {"kind": "skill", "key": "terraform"},
                    {"kind": "domain", "key": "missing"},
                ]
            },
        )

        assert response.status_code == 202
        results = response.json()["results"]
        assert [(item["outcome"], item["key"]) for item in results] == [
            ("accepted", "kubernetes"),
            ("accepted", "terraform"),
            ("not_found", "missing"),
        ]
        for item in results[:2]:
            record = _wait_for_run(client, item["runId"])
            assert record["state"] == "done", record
