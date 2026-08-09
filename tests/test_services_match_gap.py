from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import cast

import pytest

import resume_agent.services.match_gap as match_gap_module
from resume_agent.db import get_session, init_db, make_engine
from resume_agent.services.match_gap import refresh_clusters, slugify_domain
from resume_agent.taxonomy.classification import (
    ClassificationMetrics,
    ClassificationOutcome,
)
from resume_agent.taxonomy.clusters import (
    ClusterMap,
    load_cluster_map,
    save_cluster_map,
)
from resume_agent.taxonomy.state import load_taxonomy_state
from resume_agent.tracking.canonicalize import (
    IncrementalDomainGroup,
    IncrementalSkillDomains,
    SkillClusters,
)
from resume_agent.tracking.tables import Job, JobStatus


def _engine_with_target_skills(*skills: str):
    engine = make_engine("sqlite://")
    init_db(engine)
    with get_session(engine) as session:
        session.add(
            Job(
                source="manual",
                status=JobStatus.shortlisted.value,
                criteria_json={"must_have_skills": list(skills)},
            )
        )
        session.commit()
    return engine


class _AsyncCanonicalizer:
    def __init__(self, respond=None):
        self.respond = respond or (lambda new, existing: [[token] for token in new])
        self.calls = 0
        self.closed = False

    async def arun(self, prompt):
        self.calls += 1
        payload = json.loads(prompt)
        response = self.respond(payload["new"], payload["existing_canonicals"])
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(content=SkillClusters(clusters=response))

    def run(self, prompt):
        raise AssertionError("async path expected")

    async def aclose(self):
        self.closed = True


class _AsyncThemer:
    def __init__(self, respond=None):
        self.respond = respond or (
            lambda new, existing: [
                IncrementalDomainGroup(
                    new_label="Languages",
                    new_category="languages",
                    skills=list(new),
                )
            ]
        )
        self.calls = 0
        self.closed = False

    async def arun(self, prompt):
        self.calls += 1
        payload = json.loads(prompt)
        response = self.respond(payload["new"], payload["categories"])
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(content=IncrementalSkillDomains(domains=response))

    def run(self, prompt):
        raise AssertionError("async path expected")

    async def aclose(self):
        self.closed = True


def test_slugify_domain_uses_lowercase_hyphenated_alphanumeric_runs():
    assert slugify_domain("  Cloud / Data & AI  ") == "cloud-data-ai"
    assert slugify_domain("C++ / .NET") == "c-net"


def test_incremental_refresh_persists_success_and_returns_metrics(tmp_path):
    engine = _engine_with_target_skills("Python", "Rust")
    path = tmp_path / "clusters.json"
    canonicalizer = _AsyncCanonicalizer()
    themer = _AsyncThemer()

    with get_session(engine) as session:
        summary = refresh_clusters(
            session,
            canonicalizer=canonicalizer,
            themer=themer,
            path=path,
            batch_size=1,
            concurrency=2,
        )

    assert load_cluster_map(path).aliases == {"python": "python", "rust": "rust"}
    assert summary["skills"] == 2
    assert summary["canonicalBatches"] == 2
    assert summary["failedCanonicalTokens"] == 0
    assert canonicalizer.closed is True
    assert themer.closed is True


def test_existing_alias_and_theme_choices_win(tmp_path):
    engine = _engine_with_target_skills("K8s", "Kubernetes", "Go", "Rust")
    path = tmp_path / "clusters.json"
    save_cluster_map(
        ClusterMap(
            aliases={"k8s": "kubernetes", "kubernetes": "kubernetes"},
            domain_of={"kubernetes": "infra"},
            domain_label={"infra": "Infrastructure"},
        ),
        path,
    )

    with get_session(engine) as session:
        refresh_clusters(
            session,
            canonicalizer=_AsyncCanonicalizer(),
            themer=_AsyncThemer(),
            path=path,
        )

    assert load_cluster_map(path) == ClusterMap(
        aliases={
            "go": "go",
            "k8s": "kubernetes",
            "kubernetes": "kubernetes",
            "rust": "rust",
        },
        domain_of={"go": "languages", "kubernetes": "infra", "rust": "languages"},
        domain_label={"infra": "Infrastructure", "languages": "Languages"},
        category_of={"infra": "other", "languages": "languages"},
    )


def test_reconcile_failure_preserves_last_good_cluster_file(tmp_path):
    engine = _engine_with_target_skills("Python", "Rust")
    path = tmp_path / "clusters.json"
    existing = ClusterMap(
        aliases={"go": "go"},
        domain_of={"go": "languages"},
        domain_label={"languages": "Languages"},
    )
    save_cluster_map(existing, path)
    before = path.read_text(encoding="utf-8")

    def respond(new, current):
        return RuntimeError("reconcile down") if len(new) > 1 else [[new[0]]]

    with get_session(engine) as session:
        with pytest.raises(Exception, match="reconcile"):
            refresh_clusters(
                session,
                canonicalizer=_AsyncCanonicalizer(respond),
                themer=_AsyncThemer(),
                path=path,
                batch_size=1,
            )

    assert path.read_text(encoding="utf-8") == before


def test_theme_failure_remains_unassigned_and_retries_next_refresh(tmp_path):
    engine = _engine_with_target_skills("Python", "Rust")
    path = tmp_path / "clusters.json"
    canonicalizer = _AsyncCanonicalizer()

    with get_session(engine) as session:
        first = refresh_clusters(
            session,
            canonicalizer=canonicalizer,
            themer=_AsyncThemer(lambda new, existing: RuntimeError("theme down")),
            path=path,
        )
    assert load_cluster_map(path).domain_of == {}
    assert first["failedDomainTokens"] == 2

    with get_session(engine) as session:
        second = refresh_clusters(
            session,
            canonicalizer=canonicalizer,
            themer=_AsyncThemer(),
            path=path,
        )

    assert canonicalizer.calls == 2
    assert load_cluster_map(path).domain_of == {
        "python": "languages",
        "rust": "languages",
    }
    assert second["failedDomainTokens"] == 0


def test_refresh_clusters_serializes_concurrent_calls(tmp_path, monkeypatch):
    engine = _engine_with_target_skills("Python")
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()
    calls = 0

    async def classify(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            first_entered.set()
            assert release_first.wait(timeout=2)
        else:
            second_entered.set()
        return ClassificationOutcome(
            additions=ClusterMap.empty(),
            failures=(),
            metrics=ClassificationMetrics(0, 0, 0, 0, 0),
        )

    monkeypatch.setattr(match_gap_module, "classify_incrementally", classify)

    def run():
        with get_session(engine) as session:
            return refresh_clusters(
                session,
                canonicalizer=_AsyncCanonicalizer(),
                themer=_AsyncThemer(),
                path=tmp_path / "clusters.json",
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run)
        assert first_entered.wait(timeout=1)
        second = pool.submit(run)
        try:
            assert not second_entered.wait(timeout=0.2)
        finally:
            release_first.set()
        first.result(timeout=2)
        second.result(timeout=2)

    assert second_entered.is_set()


def test_refresh_keeps_profile_alias_tokens_without_job_demand(tmp_path):
    engine = _engine_with_target_skills()
    path = tmp_path / "cluster_map.json"
    save_cluster_map(
        ClusterMap(aliases={"k8s": "kubernetes", "kubernetes": "kubernetes"}),
        path,
    )
    with get_session(engine) as session:
        refresh_clusters(
            session,
            canonicalizer=_AsyncCanonicalizer(),
            themer=_AsyncThemer(),
            path=path,
            extra_tokens={"kubernetes", "k8s"},
        )
    kept = load_cluster_map(path)
    assert kept.aliases["k8s"] == "kubernetes"
    assert kept.aliases["kubernetes"] == "kubernetes"


def test_refresh_keeps_override_only_alias_head_without_job_demand(tmp_path):
    engine = _engine_with_target_skills()
    path = tmp_path / "cluster_map.json"
    save_cluster_map(
        ClusterMap(aliases={"golang": "go", "go": "go"}),
        path,
    )
    with get_session(engine) as session:
        refresh_clusters(
            session,
            canonicalizer=_AsyncCanonicalizer(),
            themer=_AsyncThemer(),
            path=path,
            extra_tokens={"golang", "go"},
        )
    kept = load_cluster_map(path)
    assert kept.aliases == {"go": "go", "golang": "go"}


def test_scoped_refresh_changes_only_requested_unassigned_skills(tmp_path):
    engine = _engine_with_target_skills("Assigned", "Alpha", "Beta", "Hidden")
    path = tmp_path / "cluster_map.json"
    original = ClusterMap(
        aliases={
            "assigned": "assigned",
            "hidden": "hidden",
        },
        domain_of={"assigned": "stable-domain"},
        domain_label={"stable-domain": "Stable domain"},
        category_of={"stable-domain": "backend-apis"},
    )
    save_cluster_map(original, path)

    with get_session(engine) as session:
        result = refresh_clusters(
            session,
            canonicalizer=_AsyncCanonicalizer(),
            themer=_AsyncThemer(
                lambda new, _categories: [
                    IncrementalDomainGroup(
                        new_label="Scoped domain",
                        new_category="languages",
                        skills=list(new),
                    )
                ]
            ),
            path=path,
            skill_keys={"alpha", "beta"},
        )

    after = load_cluster_map(path)
    assert result["processedSkillKeys"] == ["alpha", "beta"]
    assert after.domain_of["assigned"] == "stable-domain"
    assert after.aliases["hidden"] == "hidden"
    assert "hidden" not in after.domain_of
    assert after.domain_of["alpha"] == after.domain_of["beta"] == "scoped-domain"


def test_soft_target_allows_a_thirteenth_coherent_domain(tmp_path):
    engine = _engine_with_target_skills("Vision One", "Vision Two")
    path = tmp_path / "cluster_map.json"
    domains = {f"domain-{index}": f"Domain {index}" for index in range(12)}
    existing = ClusterMap(
        aliases={f"skill-{index}": f"skill-{index}" for index in range(12)},
        domain_of={f"skill-{index}": f"domain-{index}" for index in range(12)},
        domain_label=domains,
        category_of={domain_id: "ai-ml" for domain_id in domains},
    )
    save_cluster_map(existing, path)

    with get_session(engine) as session:
        result = refresh_clusters(
            session,
            canonicalizer=_AsyncCanonicalizer(),
            themer=_AsyncThemer(
                lambda new, _categories: [
                    IncrementalDomainGroup(
                        new_label="Computer Vision",
                        new_category="ai-ml",
                        skills=list(new),
                    )
                ]
            ),
            path=path,
        )

    after = load_cluster_map(path)
    assert result["domainsCreated"] == 1
    assert (
        len([domain for domain in after.category_of.values() if domain == "ai-ml"])
        == 13
    )
    assert after.domain_of["vision one"] == after.domain_of["vision two"]


def test_singleton_new_domain_is_explicitly_recorded_as_uncertain(tmp_path):
    engine = _engine_with_target_skills("Niche Tool")
    path = tmp_path / "cluster_map.json"

    with get_session(engine) as session:
        result = refresh_clusters(
            session,
            canonicalizer=_AsyncCanonicalizer(),
            themer=_AsyncThemer(),
            path=path,
        )

    assert load_cluster_map(path).domain_of == {}
    status = load_taxonomy_state(path).grouping_status["niche tool"]
    assert status.state == "uncertain"
    assert "coherence gate" in status.reason
    assert result["uncertainSkills"] == 1


def test_fifty_requested_skills_all_receive_an_outcome(tmp_path):
    tokens = {f"skill {index:02d}" for index in range(50)}
    engine = _engine_with_target_skills(*sorted(tokens))
    path = tmp_path / "cluster_map.json"

    with get_session(engine) as session:
        result = refresh_clusters(
            session,
            canonicalizer=_AsyncCanonicalizer(),
            themer=_AsyncThemer(
                lambda new, _categories: [
                    IncrementalDomainGroup(
                        new_label="Fixture skills",
                        new_category="tools-platforms",
                        skills=list(new),
                    )
                ]
            ),
            path=path,
            batch_size=10,
        )

    after = load_cluster_map(path)
    statuses = load_taxonomy_state(path).grouping_status
    outcomes = set(after.domain_of) | set(statuses)
    assert set(cast(list[str], result["processedSkillKeys"])) == tokens
    assert tokens <= outcomes
