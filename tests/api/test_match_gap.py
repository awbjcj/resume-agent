from types import SimpleNamespace

from fastapi.testclient import TestClient

import resume_agent.api.routers.match_gap as router_mod
from resume_agent.profile import effective as effective_module
from resume_agent.api.app import create_app
from resume_agent.db import get_session
from resume_agent.models.profile import (
    Bullet,
    Contact,
    Experience,
    ProfileFacts,
    Skill,
)
from resume_agent.profile.store import save_facts
from resume_agent.services.suggestions import (
    resolve_suggestion_context,
    suggestion_fingerprint,
)
from resume_agent.taxonomy.clusters import ClusterMap, save_cluster_map
from resume_agent.taxonomy.corrections import (
    TaxonomyCorrections,
    save_taxonomy_corrections,
)
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
    assert body["domains"] == []
    assert len(body["categories"]) == 20
    assert body["suggestionStatuses"] == []
    assert body["clustersStale"] is False


def test_match_gap_shadow_exposes_typed_results_from_one_profile_snapshot(
    monkeypatch,
    tmp_path,
):
    profile_dir = tmp_path / "profile"
    facts_path = profile_dir / "facts.json"
    cluster_path = profile_dir / "cluster_map.json"
    corrections_path = tmp_path / "taxonomy" / "taxonomy_corrections.json"
    save_cluster_map(
        ClusterMap(aliases={"py": "python", "python": "python"}),
        cluster_path,
    )
    save_taxonomy_corrections(TaxonomyCorrections(), corrections_path)
    save_facts(
        ProfileFacts(
            contact=Contact(name="Ada"),
            experience=[
                Experience(
                    id="experience-1",
                    company="Acme",
                    title="Engineer",
                    current=True,
                    bullets=[
                        Bullet(id="bullet-python", text="Built Python services")
                    ],
                )
            ],
            skills={"hard": [Skill(id="skill-python", name="Py")]},
        ),
        facts_path,
    )
    monkeypatch.setattr(router_mod, "_FACTS_PATH", str(facts_path))
    monkeypatch.setattr(router_mod, "_CLUSTER_PATH", str(cluster_path))
    monkeypatch.setattr(
        effective_module,
        "corrections_file_path",
        lambda: str(corrections_path),
    )
    monkeypatch.setattr(
        effective_module,
        "get_settings",
        lambda: SimpleNamespace(career_capability_mode="shadow"),
    )

    app = create_app(db_url="sqlite://")
    with TestClient(app) as client:
        with get_session(app.state.engine) as session:
            save_job(
                session,
                Job(
                    source="manual",
                    company="Acme",
                    title="Engineer",
                    jd_text="Python is required.",
                    status=JobStatus.shortlisted.value,
                    criteria_json={"tech_stack": ["Python"]},
                ),
            )
        response = client.get("/api/match-gap")

    assert response.status_code == 200
    body = response.json()
    assert body["uccmState"] == "ready"
    assert body["matchingPolicyRevision"] == "uccm-match-v1"
    assert len(body["typedRequirements"]) == 1
    assert body["typedRequirements"][0]["sourceText"] == "Python"
    assert body["matchResults"][0]["legacyCoverage"] == "covered"
    assert body["matchResults"][0]["v2"]["status"] == "verified_exact"
    assert body["profileFactsRevision"] == body["matchResults"][0]["v2"][
        "factsRevision"
    ]
    assert len(body["profileProjection"]["layers"]) == 6


def test_match_gap_projects_jobs_skills_edges_domains_and_categories(
    monkeypatch, tmp_path
):
    cluster_path = tmp_path / "cluster_map.json"
    save_cluster_map(
        ClusterMap(
            aliases={"k8s": "kubernetes", "kubernetes": "kubernetes"},
            domain_of={"kubernetes": "infra"},
            domain_label={"infra": "Cloud / Infrastructure"},
            category_of={"infra": "cloud-infra"},
        ),
        cluster_path,
    )
    monkeypatch.setattr(router_mod, "_CLUSTER_PATH", str(cluster_path))
    monkeypatch.setattr(router_mod, "_FACTS_PATH", str(tmp_path / "missing-facts.json"))
    monkeypatch.setattr(
        effective_module,
        "get_settings",
        lambda: SimpleNamespace(career_capability_mode="legacy"),
    )

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
        monkeypatch.setattr(
            effective_module,
            "get_settings",
            lambda: SimpleNamespace(career_capability_mode="uccm"),
        )
        uccm_resp = client.get("/api/match-gap")

    assert resp.status_code == 200
    assert uccm_resp.status_code == 200
    body = resp.json()
    uccm_body = uccm_resp.json()
    uccm_fields = {
        "uccmState",
        "uccmErrorCode",
        "matchingPolicyRevision",
        "profileFactsRevision",
        "assertionPolicyRevision",
        "typedRequirements",
        "matchResults",
        "profileProjection",
    }
    legacy_business_payload = {
        key: value
        for key, value in body.items()
        if key not in {"taxonomyRevision", "taxonomyManifest", *uccm_fields}
    }
    uccm_business_payload = {
        key: value
        for key, value in uccm_body.items()
        if key not in {"taxonomyRevision", "taxonomyManifest", *uccm_fields}
    }
    assert uccm_business_payload == legacy_business_payload
    assert uccm_body["taxonomyManifest"]["capabilityStatus"] == "fallback"
    assert uccm_body["taxonomyManifest"]["capabilityEffectiveMode"] == "shadow"
    assert (
        uccm_body["taxonomyManifest"]["capabilityErrorCode"]
        == "activation_report_missing"
    )
    assert (
        len(
            uccm_body["taxonomyManifest"]["capability"][
                "internalGraphVersion"
            ]
        )
        == 64
    )
    taxonomy_revision = body.pop("taxonomyRevision")
    taxonomy_manifest = body.pop("taxonomyManifest")
    override_conflicts = body.pop("overrideConflicts")
    for key in uccm_fields:
        body.pop(key)
    assert len(taxonomy_revision) == 64
    assert taxonomy_manifest["semantic"] == taxonomy_revision
    assert override_conflicts == []
    assert {**body, "categories": []} == {
        "targetTotal": 1,
        "clustersStale": False,
        "jobs": [
            {
                "id": 1,
                "company": "Stripe",
                "title": "Platform Engineer",
                "seniority": "senior",
                "status": "shortlisted",
            }
        ],
        "skills": [
            {
                "skill": "K8s",
                "domainId": "infra",
                "covered": False,
                "coverage": "gap",
                "key": "kubernetes",
                "members": {"K8s": 1, "Kubernetes": 1},
                "must": 1,
                "nice": 1,
                "tech": 0,
                "jobCount": 1,
                "groupingStatus": None,
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
        "domains": [
            {
                "id": "infra",
                "label": "Cloud / Infrastructure",
                "category": "cloud-infra",
                "essentialScore": 5,
                "popularScore": 1,
                "jobCount": 1,
                "skillCount": 1,
                "gapCount": 1,
                "adjacentCount": 0,
            }
        ],
        "categories": [],
        "suggestionStatuses": [],
        "taxonomyGeneration": None,
        "taxonomyAlgorithmVersion": "embedding-taxonomy-v1",
        "taxonomyMaintenanceDue": True,
        "unassignedCount": 0,
        "taxonomyUndoAvailable": False,
        "retiredSkills": [],
    }
    assert body["categories"][7] == {
        "slug": "cloud-infra",
        "label": "Cloud & Infrastructure",
        "kind": "hard",
    }


def test_match_gap_reports_override_conflicts(monkeypatch, tmp_path):
    from resume_agent.profile import effective as effective_module

    profile_dir = tmp_path / "profile"
    facts_path = profile_dir / "facts.json"
    cluster_path = profile_dir / "cluster_map.json"
    corrections_path = tmp_path / "taxonomy" / "taxonomy_corrections.json"
    save_facts(ProfileFacts(contact=Contact(name="A")), facts_path)
    save_cluster_map(ClusterMap(), cluster_path)
    save_taxonomy_corrections(
        TaxonomyCorrections(aliases={"js": "javascript"}), corrections_path
    )
    (profile_dir / "overrides.yaml").write_text(
        "alias:\n  js: typescript\n", encoding="utf-8"
    )
    monkeypatch.setattr(router_mod, "_FACTS_PATH", str(facts_path))
    monkeypatch.setattr(router_mod, "_CLUSTER_PATH", str(cluster_path))
    monkeypatch.setattr(
        effective_module, "corrections_file_path", lambda: str(corrections_path)
    )

    app = create_app(db_url="sqlite://")
    with TestClient(app) as client:
        payload = client.get("/api/match-gap").json()

    assert payload["overrideConflicts"] == [
        {
            "token": "js",
            "correctionHead": "javascript",
            "overrideHead": "typescript",
            "resolution": "override",
        }
    ]


def test_match_gap_includes_canonical_persisted_suggestion_status(
    monkeypatch, tmp_path
):
    cluster_path = tmp_path / "cluster_map.json"
    cluster_map = ClusterMap(
        aliases={"python": "python"},
        domain_of={"python": "backend"},
        domain_label={"backend": "Backend"},
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
