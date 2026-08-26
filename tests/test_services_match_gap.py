from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import cast

import pytest

import resume_agent.services.match_gap as match_gap_module
from resume_agent.db import get_session, init_db, make_engine
from resume_agent.progress import ProgressReporter
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
        if isinstance(response, IncrementalSkillDomains):
            return SimpleNamespace(content=response)
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


def test_refresh_progress_uses_monotonic_phase_indices(tmp_path):
    class _Reporter(ProgressReporter):
        def __init__(self):
            self.phases: list[int] = []

        def begin(self, _total, _label, *, phase_index=None, **_extra):
            assert phase_index is not None
            self.phases.append(phase_index)

        def step(self, _current, **_extra):
            pass

        def checkpoint(self):
            pass

    reporter = _Reporter()
    engine = _engine_with_target_skills("Python", "Rust")
    with get_session(engine) as session:
        refresh_clusters(
            session,
            canonicalizer=_AsyncCanonicalizer(),
            themer=_AsyncThemer(),
            path=tmp_path / "clusters.json",
            batch_size=1,
            reporter=reporter,
        )

    assert reporter.phases == list(range(1, len(reporter.phases) + 1))
    assert len(reporter.phases) >= 3


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


def test_model_call_failure_is_never_placed_by_the_floor(tmp_path):
    """An outage is not a judgment, so the placement floor must not absorb it.

    Filing a skill because the request failed would convert a transient error
    into a permanent misplacement, and would also hide the outage.
    """
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


def test_incomplete_canonical_output_stays_in_the_backlog(tmp_path):
    engine = _engine_with_target_skills("Rust")
    path = tmp_path / "clusters.json"
    incomplete = _AsyncCanonicalizer(lambda _new, _current: [])

    with get_session(engine) as session:
        first = refresh_clusters(
            session,
            canonicalizer=incomplete,
            themer=_AsyncThemer(),
            path=path,
        )

    assert load_cluster_map(path) == ClusterMap.empty()
    assert first["failedCanonicalTokens"] == 1
    assert load_taxonomy_state(path).grouping_status["rust"].phase == "canonicalize"

    recovered = _AsyncCanonicalizer()
    with get_session(engine) as session:
        second = refresh_clusters(
            session,
            canonicalizer=recovered,
            themer=_AsyncThemer(),
            path=path,
        )

    assert recovered.calls > 0
    assert load_cluster_map(path).domain_of == {"rust": "languages"}
    assert second["remainingUnassigned"] == 0


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


def test_singleton_new_domain_is_placed_by_the_escalation_pass(tmp_path):
    """A lone new skill is the common case, so one pass declining is not the end.

    The first pass still refuses to mint a domain for a single token, but the
    escalation pass sees the whole taxonomy and may place it -- otherwise every
    genuinely novel skill would be permanently unassignable.
    """

    engine = _engine_with_target_skills("Niche Tool")
    path = tmp_path / "cluster_map.json"

    with get_session(engine) as session:
        result = refresh_clusters(
            session,
            canonicalizer=_AsyncCanonicalizer(),
            themer=_AsyncThemer(),
            path=path,
        )

    assert load_cluster_map(path).domain_of == {"niche tool": "languages"}
    assert "niche tool" not in load_taxonomy_state(path).grouping_status
    assert result["uncertainSkills"] == 0
    assert result["remainingUnassigned"] == 0


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


def _languages(new, _categories):
    return [
        IncrementalDomainGroup(
            new_label="Languages", new_category="languages", skills=list(new)
        )
    ]


def test_a_token_naming_no_skill_is_retired_and_leaves_the_backlog(tmp_path):
    """Retirement is what stops the backlog from re-buying the same verdict.

    Without a terminal disposition, a phrase like an experience requirement is
    re-sent to the model on every single run, forever.
    """

    engine = _engine_with_target_skills("Python", "Ten Years Of Experience")
    path = tmp_path / "cluster_map.json"

    def respond(new, _categories):
        real = [token for token in new if token == "python"]
        return IncrementalSkillDomains(
            domains=_languages(real, None) if real else [],
            not_skills=[token for token in new if token != "python"],
        )

    with get_session(engine) as session:
        first = refresh_clusters(
            session,
            canonicalizer=_AsyncCanonicalizer(),
            themer=_AsyncThemer(respond),
            path=path,
        )

    assert first["retiredSkills"] == ["ten years of experience"]
    assert load_cluster_map(path).domain_of == {"python": "languages"}
    assert "ten years of experience" in load_taxonomy_state(path).retired_skills

    repeat = _AsyncThemer(respond)
    with get_session(engine) as session:
        second = refresh_clusters(
            session,
            canonicalizer=_AsyncCanonicalizer(),
            themer=repeat,
            path=path,
        )

    assert second["processedSkillKeys"] == []
    assert repeat.calls == 0


def test_a_retired_skill_can_be_restored_to_the_backlog(tmp_path):
    """A wrong retirement must be one call from being undone."""

    from resume_agent.services.match_gap import restore_skills

    engine = _engine_with_target_skills("Kubeflow")
    path = tmp_path / "cluster_map.json"

    def retire_everything(new, _categories):
        return IncrementalSkillDomains(domains=[], not_skills=list(new))

    with get_session(engine) as session:
        refresh_clusters(
            session,
            canonicalizer=_AsyncCanonicalizer(),
            themer=_AsyncThemer(retire_everything),
            path=path,
        )
    assert "kubeflow" in load_taxonomy_state(path).retired_skills

    restored = restore_skills(path=path, skill_keys={"Kubeflow"})
    assert restored == {"restored": 1, "restoredSkills": ["kubeflow"]}
    assert load_taxonomy_state(path).retired_skills == {}

    with get_session(engine) as session:
        again = refresh_clusters(
            session,
            canonicalizer=_AsyncCanonicalizer(),
            themer=_AsyncThemer(_languages),
            path=path,
        )
    assert again["processedSkillKeys"] == ["kubeflow"]
    assert load_cluster_map(path).domain_of == {"kubeflow": "languages"}


def test_a_skill_that_failed_before_goes_straight_to_escalation(tmp_path):
    """Repeat runs must differ, or clicking Regroup again is a pure replay.

    A token carrying a recorded failure skips the first pass entirely and is
    retried against the whole taxonomy with the escalation classifier.
    """

    engine = _engine_with_target_skills("Python")
    path = tmp_path / "cluster_map.json"

    with get_session(engine) as session:
        refresh_clusters(
            session,
            canonicalizer=_AsyncCanonicalizer(),
            themer=_AsyncThemer(lambda new, categories: RuntimeError("themer down")),
            path=path,
        )
    assert load_taxonomy_state(path).grouping_status["python"].state == "failed"

    first_pass = _AsyncThemer(_languages)
    escalation = _AsyncThemer(_languages)
    with get_session(engine) as session:
        result = refresh_clusters(
            session,
            canonicalizer=_AsyncCanonicalizer(),
            themer=first_pass,
            escalation_themer=escalation,
            path=path,
        )

    assert result["elapsedMs"] >= result["modelElapsedMs"]
    assert result["maxInFlight"] <= 2
    assert result["operationWaitMs"] >= 0
    assert result["snapshotMs"] >= 0
    assert result["retrievalMs"] >= 0
    assert result["commitMs"] >= 0

    assert first_pass.calls == 0
    assert escalation.calls == 1
    assert result["escalatedSkills"] == 1
    assert load_cluster_map(path).domain_of == {"python": "languages"}
    assert "python" not in load_taxonomy_state(path).grouping_status


def test_the_escalation_cap_defers_instead_of_flooring(tmp_path, monkeypatch):
    """What the per-run bound skips has not been judged, so it must not be filed.

    The escalation cap exists to bound cost. Treating what it defers as
    "unplaceable" would file skills the expensive pass never even saw.
    """

    from resume_agent.config import env_settings

    monkeypatch.setenv("TAXONOMY_ESCALATION_MAX_SKILLS", "1")
    env_settings.cache_clear()

    engine = _engine_with_target_skills("Alpha Skill", "Beta Skill")
    path = tmp_path / "cluster_map.json"

    # The first pass refuses everything; only escalation can place a token.
    def decline(_new, _categories):
        return []

    escalation = _AsyncThemer(_languages)
    try:
        with get_session(engine) as session:
            result = refresh_clusters(
                session,
                canonicalizer=_AsyncCanonicalizer(),
                themer=_AsyncThemer(decline),
                escalation_themer=escalation,
                path=path,
            )
    finally:
        env_settings.cache_clear()

    placed = load_cluster_map(path).domain_of
    assert placed == {"alpha skill": "languages"}
    assert result["escalatedSkills"] == 1
    assert result["placedByFallback"] == 0
    # The deferred token keeps a status so it escalates first next run.
    assert "beta skill" in load_taxonomy_state(path).grouping_status
