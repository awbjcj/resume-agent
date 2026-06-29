from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

import resume_agent.services.match_gap as match_gap_module
from resume_agent.db import get_session, init_db, make_engine
from resume_agent.services.match_gap import refresh_clusters, slugify_theme
from resume_agent.taxonomy.classification import (
    ClassificationMetrics,
    ClassificationOutcome,
)
from resume_agent.taxonomy.clusters import ClusterMap, load_cluster_map, save_cluster_map
from resume_agent.tracking.canonicalize import (
    IncrementalSkillThemes,
    IncrementalThemeGroup,
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
                IncrementalThemeGroup(new_label="Languages", skills=list(new))
            ]
        )
        self.calls = 0
        self.closed = False

    async def arun(self, prompt):
        self.calls += 1
        payload = json.loads(prompt)
        response = self.respond(payload["new"], payload["existing_themes"])
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(content=IncrementalSkillThemes(themes=response))

    def run(self, prompt):
        raise AssertionError("async path expected")

    async def aclose(self):
        self.closed = True


def test_slugify_theme_uses_lowercase_hyphenated_alphanumeric_runs():
    assert slugify_theme("  Cloud / Data & AI  ") == "cloud-data-ai"
    assert slugify_theme("C++ / .NET") == "c-net"


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
    engine = _engine_with_target_skills("K8s", "Kubernetes", "Go")
    path = tmp_path / "clusters.json"
    save_cluster_map(
        ClusterMap(
            aliases={"k8s": "kubernetes", "kubernetes": "kubernetes"},
            theme_of={"kubernetes": "infra"},
            theme_label={"infra": "Infrastructure"},
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
        aliases={"go": "go", "k8s": "kubernetes", "kubernetes": "kubernetes"},
        theme_of={"go": "languages", "kubernetes": "infra"},
        theme_label={"infra": "Infrastructure", "languages": "Languages"},
    )


def test_reconcile_failure_preserves_last_good_cluster_file(tmp_path):
    engine = _engine_with_target_skills("Python", "Rust")
    path = tmp_path / "clusters.json"
    existing = ClusterMap(
        aliases={"go": "go"},
        theme_of={"go": "languages"},
        theme_label={"languages": "Languages"},
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
    engine = _engine_with_target_skills("Python")
    path = tmp_path / "clusters.json"
    canonicalizer = _AsyncCanonicalizer()

    with get_session(engine) as session:
        first = refresh_clusters(
            session,
            canonicalizer=canonicalizer,
            themer=_AsyncThemer(lambda new, existing: RuntimeError("theme down")),
            path=path,
        )
    assert load_cluster_map(path).theme_of == {}
    assert first["failedThemeTokens"] == 1

    with get_session(engine) as session:
        second = refresh_clusters(
            session,
            canonicalizer=canonicalizer,
            themer=_AsyncThemer(),
            path=path,
        )

    assert canonicalizer.calls == 2
    assert load_cluster_map(path).theme_of == {"python": "languages"}
    assert second["failedThemeTokens"] == 0


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
