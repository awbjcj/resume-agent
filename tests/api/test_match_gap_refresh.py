import json
import threading
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

import resume_tailor_harness.api.routers.match_gap as router_mod
import resume_tailor_harness.tracking.canonicalize as canonicalize
from resume_tailor_harness.api.app import create_app
from resume_tailor_harness.db import get_session
from resume_tailor_harness.models.profile import Contact, ProfileFacts, Skill
from resume_tailor_harness.profile.matrix import load_matrix
from resume_tailor_harness.profile.store import save_facts
from resume_tailor_harness.tracking.canonicalize import (
    IncrementalDomainGroup,
    IncrementalSkillDomains,
    SkillClusters,
    TaxonomyMaintenanceAction,
    TaxonomyMaintenancePlan,
)
from resume_tailor_harness.tracking.repository import save_job
from resume_tailor_harness.tracking.tables import Job, JobStatus
from resume_tailor_harness.taxonomy.groups import group_map_path, save_group_map
from resume_tailor_harness.taxonomy.clusters import (
    ClusterMap,
    load_cluster_map,
    save_cluster_map,
)


class _AsyncCanonicalizer:
    def __init__(self, wait: threading.Event | None = None):
        self.wait = wait

    async def arun(self, prompt):
        if self.wait is not None:
            self.wait.wait(timeout=2)
        payload = json.loads(prompt)
        return SimpleNamespace(
            content=SkillClusters.model_validate(
                {"clusters": [[token] for token in payload["new"]]}
            )
        )

    def run(self, prompt):
        raise AssertionError("async path expected")


class _AsyncThemer:
    async def arun(self, prompt):
        payload = json.loads(prompt)
        return SimpleNamespace(
            content=IncrementalSkillDomains(
                domains=[
                    IncrementalDomainGroup(
                        new_label="Cloud / Infrastructure",
                        new_category="cloud-infra",
                        skills=list(payload["new"]),
                    )
                ]
            )
        )

    def run(self, prompt):
        raise AssertionError("async path expected")


class _MaintenanceJudge:
    async def arun(self, _prompt):
        return SimpleNamespace(
            content=TaxonomyMaintenancePlan(
                actions=[
                    TaxonomyMaintenanceAction(
                        kind="rename",
                        domain_id="frontend",
                        label="Frontend Frameworks",
                        confidence="high",
                    )
                ]
            )
        )

    def run(self, _prompt):
        raise AssertionError("async path expected")


def _seed_job(app):
    with get_session(app.state.engine) as session:
        save_job(
            session,
            Job(
                source="manual",
                company="C",
                title="T",
                status=JobStatus.shortlisted.value,
                criteria_json={"must_have_skills": ["k8s", "React"]},
            ),
        )


def _wait_for_terminal(client: TestClient, run_id: str):
    for _ in range(100):
        record = client.get(f"/api/runs/{run_id}").json()
        if record["state"] in ("done", "error"):
            return record
        time.sleep(0.02)
    raise AssertionError("refresh-clusters run did not finish in time")


def test_refresh_clusters_run_completes(monkeypatch, tmp_path):
    monkeypatch.setattr(
        canonicalize, "build_incremental_canonicalizer_agent", _AsyncCanonicalizer
    )
    monkeypatch.setattr(canonicalize, "build_incremental_themer_agent", _AsyncThemer)
    monkeypatch.setattr(canonicalize, "build_escalation_themer_agent", _AsyncThemer)
    monkeypatch.setattr(router_mod, "_FACTS_PATH", str(tmp_path / "facts.json"))
    monkeypatch.setattr(router_mod, "_CLUSTER_PATH", str(tmp_path / "cluster_map.json"))

    app = create_app(db_url="sqlite://", runs_root=tmp_path)
    with TestClient(app) as client:
        _seed_job(app)
        response = client.post("/api/match-gap/refresh-clusters")
        assert response.status_code == 202
        record = _wait_for_terminal(client, response.json()["runId"])

    assert record["state"] == "done"
    assert record["result"]["skills"] == 2
    assert record["result"]["failedCanonicalTokens"] == 0
    assert record["result"]["matrixRegenerated"] is False


def test_refresh_cluster_launches_are_coalesced_while_active(monkeypatch, tmp_path):
    release = threading.Event()
    canonicalizer = _AsyncCanonicalizer(release)
    monkeypatch.setattr(
        canonicalize,
        "build_incremental_canonicalizer_agent",
        lambda: canonicalizer,
    )
    monkeypatch.setattr(canonicalize, "build_incremental_themer_agent", _AsyncThemer)
    monkeypatch.setattr(canonicalize, "build_escalation_themer_agent", _AsyncThemer)
    monkeypatch.setattr(router_mod, "_FACTS_PATH", str(tmp_path / "facts.json"))
    monkeypatch.setattr(router_mod, "_CLUSTER_PATH", str(tmp_path / "cluster_map.json"))

    app = create_app(db_url="sqlite://", runs_root=tmp_path)
    with TestClient(app) as client:
        _seed_job(app)
        first = client.post("/api/match-gap/refresh-clusters").json()["runId"]
        second = client.post("/api/match-gap/refresh-clusters").json()["runId"]
        assert first == second
        release.set()
        assert _wait_for_terminal(client, first)["state"] == "done"
        third = client.post("/api/match-gap/refresh-clusters").json()["runId"]
        assert _wait_for_terminal(client, third)["state"] == "done"

    assert third != first


def test_refresh_regenerates_matrix_from_bound_facts(monkeypatch, tmp_path):
    monkeypatch.setattr(
        canonicalize, "build_incremental_canonicalizer_agent", _AsyncCanonicalizer
    )
    monkeypatch.setattr(canonicalize, "build_incremental_themer_agent", _AsyncThemer)
    monkeypatch.setattr(canonicalize, "build_escalation_themer_agent", _AsyncThemer)
    facts_path = tmp_path / "facts.json"
    cluster_path = tmp_path / "cluster_map.json"
    monkeypatch.setattr(router_mod, "_FACTS_PATH", str(facts_path))
    monkeypatch.setattr(router_mod, "_CLUSTER_PATH", str(cluster_path))
    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        skills={"Platforms": [Skill(name="Kubernetes", aliases=["k8s"])]},
    )
    save_facts(facts, facts_path)
    save_group_map(
        {"kubernetes": "cloud-infra"},
        group_map_path(facts_path.parent),
    )

    app = create_app(db_url="sqlite://", runs_root=tmp_path)
    with TestClient(app) as client:
        _seed_job(app)
        response = client.post("/api/match-gap/refresh-clusters")
        record = _wait_for_terminal(client, response.json()["runId"])
        payload = client.get("/api/match-gap").json()

    assert record["state"] == "done"
    assert record["result"]["matrixRegenerated"] is True
    matrix = load_matrix(tmp_path / "matrix.json")
    assert matrix is not None
    assert len(payload["taxonomyRevision"]) == 64
    assert payload["taxonomyManifest"]["semantic"] == payload["taxonomyRevision"]
    assert matrix.taxonomy_revision == payload["taxonomyRevision"]
    assert matrix.rows[0].group == "cloud-infra"


def test_scoped_refresh_processes_only_visible_unassigned_keys(monkeypatch, tmp_path):
    monkeypatch.setattr(
        canonicalize, "build_incremental_canonicalizer_agent", _AsyncCanonicalizer
    )
    monkeypatch.setattr(canonicalize, "build_incremental_themer_agent", _AsyncThemer)
    monkeypatch.setattr(canonicalize, "build_escalation_themer_agent", _AsyncThemer)
    cluster_path = tmp_path / "cluster_map.json"
    save_cluster_map(
        ClusterMap(
            aliases={"react": "react"},
            domain_of={"react": "frontend"},
            domain_label={"frontend": "Frontend"},
            category_of={"frontend": "frontend-web"},
        ),
        cluster_path,
    )
    monkeypatch.setattr(router_mod, "_FACTS_PATH", str(tmp_path / "facts.json"))
    monkeypatch.setattr(router_mod, "_CLUSTER_PATH", str(cluster_path))
    app = create_app(db_url="sqlite://", runs_root=tmp_path)

    with TestClient(app) as client:
        _seed_job(app)
        response = client.post(
            "/api/match-gap/refresh-clusters",
            json={"skillKeys": [" K8S ", "k8s", "react", "missing"]},
        )
        record = _wait_for_terminal(client, response.json()["runId"])
        graph = client.get("/api/match-gap").json()

    assert record["state"] == "done"
    assert record["result"]["processedSkillKeys"] == ["k8s"]
    assert record["result"]["skippedAlreadyAssigned"] == ["react"]
    assert record["result"]["skippedUnknown"] == ["missing"]
    # The scoped key now ends the refresh with a home rather than an
    # explanation: one pass declining is no longer a terminal outcome.
    k8s = next(skill for skill in graph["skills"] if skill["key"] == "k8s")
    assert k8s["groupingStatus"] is None
    assert k8s["domainId"] is not None
    after = load_cluster_map(cluster_path)
    assert after.domain_of["react"] == "frontend"
    assert "react" not in after.aliases or after.aliases["react"] == "react"


def test_different_scoped_refresh_sets_are_not_coalesced(monkeypatch, tmp_path):
    release = threading.Event()
    monkeypatch.setattr(
        canonicalize,
        "build_incremental_canonicalizer_agent",
        lambda: _AsyncCanonicalizer(release),
    )
    monkeypatch.setattr(canonicalize, "build_incremental_themer_agent", _AsyncThemer)
    monkeypatch.setattr(canonicalize, "build_escalation_themer_agent", _AsyncThemer)
    monkeypatch.setattr(router_mod, "_FACTS_PATH", str(tmp_path / "facts.json"))
    monkeypatch.setattr(router_mod, "_CLUSTER_PATH", str(tmp_path / "cluster_map.json"))
    app = create_app(db_url="sqlite://", runs_root=tmp_path)

    with TestClient(app) as client:
        _seed_job(app)
        first = client.post(
            "/api/match-gap/refresh-clusters", json={"skillKeys": ["k8s"]}
        ).json()["runId"]
        second = client.post(
            "/api/match-gap/refresh-clusters", json={"skillKeys": ["react"]}
        ).json()["runId"]
        release.set()
        assert _wait_for_terminal(client, first)["state"] == "done"
        assert _wait_for_terminal(client, second)["state"] == "done"

    assert first != second


def test_maintenance_and_undo_runs_are_exposed_by_the_match_gap_api(
    monkeypatch, tmp_path
):
    cluster_path = tmp_path / "cluster_map.json"
    save_cluster_map(
        ClusterMap(
            aliases={"react": "react"},
            domain_of={"react": "frontend"},
            domain_label={"frontend": "Frontend"},
            category_of={"frontend": "frontend-web"},
        ),
        cluster_path,
    )
    monkeypatch.setattr(
        canonicalize, "build_taxonomy_maintenance_agent", _MaintenanceJudge
    )
    monkeypatch.setattr(
        "resume_tailor_harness.taxonomy.embeddings._provider_from_settings", lambda: None
    )
    monkeypatch.setattr(router_mod, "_FACTS_PATH", str(tmp_path / "facts.json"))
    monkeypatch.setattr(router_mod, "_CLUSTER_PATH", str(cluster_path))
    app = create_app(db_url="sqlite://", runs_root=tmp_path)

    with TestClient(app) as client:
        maintain = client.post("/api/match-gap/maintain-taxonomy")
        maintained = _wait_for_terminal(client, maintain.json()["runId"])
        undo = client.post("/api/match-gap/undo-taxonomy-maintenance")
        restored = _wait_for_terminal(client, undo.json()["runId"])

    assert maintained["state"] == "done"
    assert maintained["result"]["changed"] is True
    assert restored["state"] == "done"
    assert load_cluster_map(cluster_path).domain_label["frontend"] == "Frontend"


def test_retired_skills_are_visible_and_restorable(monkeypatch, tmp_path):
    """A retirement leaves the backlog, so it must stay visible and reversible.

    Retired tokens are subtracted from demand entirely; without a surface they
    would be both invisible and permanent.
    """

    from resume_tailor_harness.taxonomy.state import load_taxonomy_state, set_grouping_statuses

    cluster_path = tmp_path / "cluster_map.json"
    save_cluster_map(ClusterMap(aliases={"python": "python"}), cluster_path)
    set_grouping_statuses(
        cluster_path,
        assigned=set(),
        statuses={},
        retired={"ten years of experience": "not a skill"},
    )

    monkeypatch.setattr(router_mod, "_FACTS_PATH", str(tmp_path / "facts.json"))
    monkeypatch.setattr(router_mod, "_CLUSTER_PATH", str(cluster_path))
    app = create_app(db_url="sqlite://", runs_root=tmp_path)

    with TestClient(app) as client:
        payload = client.get("/api/match-gap").json()
        assert [item["key"] for item in payload["retiredSkills"]] == [
            "ten years of experience"
        ]

        restored = client.post(
            "/api/match-gap/restore-skills",
            json={"skillKeys": ["Ten Years Of Experience"]},
        )
        assert restored.status_code == 200
        assert restored.json() == {
            "restored": 1,
            "restoredSkills": ["ten years of experience"],
        }
        assert client.get("/api/match-gap").json()["retiredSkills"] == []

    assert load_taxonomy_state(cluster_path).retired_skills == {}
