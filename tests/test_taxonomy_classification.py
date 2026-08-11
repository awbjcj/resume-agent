import asyncio
import json
from types import SimpleNamespace

import pytest

from resume_agent.taxonomy.classification import (
    ClassificationFailure,
    ClassificationMetrics,
    ClassificationOutcome,
    ReconcileError,
    _category_context,
    _project_domains,
    classify_incrementally,
)
from resume_agent.taxonomy.clusters import ClusterMap
from resume_agent.taxonomy.vocabulary import SKILL_GROUPS
from resume_agent.tracking.canonicalize import (
    IncrementalDomainGroup,
    IncrementalSkillDomains,
    SkillClusters,
)


def test_classification_contracts_hold_additions_failures_and_metrics():
    failure = ClassificationFailure(
        phase="canonicalize", tokens=("rust",), message="provider down"
    )
    metrics = ClassificationMetrics(
        canonical_batches=1,
        domain_batches=0,
        prompt_bytes=42,
        max_in_flight=1,
        elapsed_ms=10,
    )
    outcome = ClassificationOutcome(
        additions=ClusterMap(aliases={"python": "python"}),
        failures=(failure,),
        metrics=metrics,
    )

    assert outcome.failures == (failure,)
    assert outcome.metrics.prompt_bytes == 42


class _Canonicalizer:
    def __init__(self, respond=None):
        self.respond = respond or (lambda new, existing: [[token] for token in new])
        self.calls: list[dict] = []

    async def arun(self, prompt):
        payload = json.loads(prompt)
        self.calls.append(payload)
        response = self.respond(payload["new"], payload["existing_canonicals"])
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(content=SkillClusters(clusters=response))

    def run(self, prompt):
        raise AssertionError("async path expected")


class _Themer:
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
        self.calls: list[dict] = []

    async def arun(self, prompt):
        payload = json.loads(prompt)
        self.calls.append(payload)
        response = self.respond(payload["new"], payload["categories"])
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(content=IncrementalSkillDomains(domains=response))

    def run(self, prompt):
        raise AssertionError("async path expected")


def _classify(*, demanded, existing=None, canonicalizer=None, themer=None, **kwargs):
    return asyncio.run(
        classify_incrementally(
            demanded_tokens=set(demanded),
            existing=existing or ClusterMap.empty(),
            canonicalizer=canonicalizer or _Canonicalizer(),
            themer=themer or _Themer(),
            batch_size=kwargs.pop("batch_size", 60),
            concurrency=kwargs.pop("concurrency", 4),
            category_cap=kwargs.pop("category_cap", 12),
            reconcile_batch_size=kwargs.pop("reconcile_batch_size", 150),
            **kwargs,
        )
    )


def test_warm_complete_map_makes_no_model_calls():
    canonicalizer = _Canonicalizer()
    themer = _Themer()
    existing = ClusterMap(
        aliases={"python": "python"},
        domain_of={"python": "languages"},
        domain_label={"languages": "Languages"},
    )

    outcome = _classify(
        demanded={"python"},
        existing=existing,
        canonicalizer=canonicalizer,
        themer=themer,
    )

    assert canonicalizer.calls == []
    assert themer.calls == []
    assert outcome.additions == ClusterMap.empty()
    assert outcome.metrics.prompt_bytes == 0


def test_reconcile_merges_cross_batch_synonyms_and_themes_the_head():
    def respond(new, existing):
        if set(new) == {"k8s", "kube"}:
            return [["k8s", "kube"]]
        return [[token] for token in new]

    outcome = _classify(
        demanded={"k8s", "kube"},
        canonicalizer=_Canonicalizer(respond),
        batch_size=1,
    )

    assert outcome.additions.aliases == {"k8s": "k8s", "kube": "k8s"}
    assert outcome.additions.domain_of == {"k8s": "languages"}
    assert outcome.metrics.canonical_batches == 2


def test_reconcile_preserves_aliases_that_already_target_a_stable_canonical():
    existing = ClusterMap(
        aliases={"kubernetes": "kubernetes"},
        domain_of={"kubernetes": "cloud"},
        domain_label={"cloud": "Cloud"},
    )

    def respond(new, current):
        if set(new) == {"k8s", "rust"}:
            return [["kubernetes", "k8s"], ["rust"]]
        return [[token] for token in new]

    outcome = _classify(
        demanded={"k8s", "kubernetes", "rust"},
        existing=existing,
        canonicalizer=_Canonicalizer(respond),
    )

    assert outcome.additions.aliases == {"k8s": "kubernetes", "rust": "rust"}


def test_failed_canonical_batch_stays_absent_and_retryable():
    def respond(new, existing):
        return RuntimeError("provider down") if new == ["rust"] else [[token] for token in new]

    outcome = _classify(
        demanded={"python", "rust"},
        canonicalizer=_Canonicalizer(respond),
        batch_size=1,
    )

    assert outcome.additions.aliases == {"python": "python"}
    assert "rust" not in outcome.additions.domain_of
    assert any(f.phase == "canonicalize" and f.tokens == ("rust",) for f in outcome.failures)


def test_ambiguous_existing_canonicals_reject_the_new_token():
    existing = ClusterMap(
        aliases={"kubernetes": "kubernetes", "containers": "containers"}
    )
    canonicalizer = _Canonicalizer(
        lambda new, current: [["kubernetes", "containers", "k8s"]]
    )

    outcome = _classify(
        demanded={"kubernetes", "containers", "k8s"},
        existing=existing,
        canonicalizer=canonicalizer,
    )

    assert "k8s" not in outcome.additions.aliases


def test_reconcile_call_failure_is_fatal():
    # A genuine model CALL failure is transactional: abort so the caller keeps
    # the last-good file rather than saving a half-reconciled map.
    def respond(new, existing):
        if len(new) > 1:
            return RuntimeError("reconcile down")
        return [[new[0]]]

    with pytest.raises(ReconcileError, match="reconcile"):
        _classify(
            demanded={"python", "rust"},
            canonicalizer=_Canonicalizer(respond),
            batch_size=1,
        )


def test_reconcile_partial_coverage_keeps_heads_and_is_not_fatal():
    # Reproduces the reported failure: the reconcile call SUCCEEDS and returns
    # well-formed clusters, but silently omits a head (what a real model does
    # with a large, noisy backlog). The omitted head is already a valid
    # canonical from its batch, so it must keep itself instead of aborting the
    # whole run.
    def respond(new, existing):
        if len(new) > 1:  # the reconcile call over both new heads
            return [[token] for token in new if token != "rust"]
        return [[new[0]]]

    outcome = _classify(
        demanded={"python", "rust"},
        canonicalizer=_Canonicalizer(respond),
        batch_size=1,
    )

    assert outcome.additions.aliases == {"python": "python", "rust": "rust"}
    assert any(
        f.phase == "canonicalize" and "rust" in f.tokens for f in outcome.failures
    )


def test_reconcile_shards_large_new_head_sets_instead_of_one_call():
    # Simulates a large fresh-corpus backlog: every alias batch mints its own
    # singleton head, so `new_heads` ends up far bigger than any one call
    # should reasonably receive. A well-behaved reconcile phase must chunk
    # this instead of sending every head in a single unsharded call.
    tokens = {f"skill{index}" for index in range(12)}
    canonicalizer = _Canonicalizer()

    outcome = _classify(
        demanded=tokens,
        canonicalizer=canonicalizer,
        batch_size=60,
        reconcile_batch_size=4,
    )

    assert outcome.additions.aliases == {token: token for token in tokens}
    # First call is the single alias batch (batch_size=60 covers all 12 at
    # once); every subsequent call is a reconcile chunk and must respect
    # reconcile_batch_size regardless of how large batch_size is.
    reconcile_calls = canonicalizer.calls[1:]
    assert len(reconcile_calls) == 3
    assert all(len(call["new"]) <= 4 for call in reconcile_calls)


def test_existing_unthemed_canonical_is_themed_without_canonical_call():
    canonicalizer = _Canonicalizer()
    existing = ClusterMap(aliases={"python": "python"})

    outcome = _classify(
        demanded={"python"}, existing=existing, canonicalizer=canonicalizer
    )

    assert canonicalizer.calls == []
    assert outcome.additions.domain_of == {"python": "languages"}


def test_legacy_category_hint_follows_an_alias_to_its_canonical():
    existing = ClusterMap(aliases={"kubernetes": "kubernetes"})
    canonicalizer = _Canonicalizer(
        lambda _new, _existing: [["kubernetes", "k8s"]]
    )
    themer = _Themer()

    _classify(
        demanded={"k8s"},
        existing=existing,
        canonicalizer=canonicalizer,
        themer=themer,
        category_hints={"k8s": "cloud-infra"},
    )

    assert themer.calls[0]["category_hints"] == {
        "kubernetes": "cloud-infra"
    }


def test_failed_domain_batch_keeps_alias_but_not_domain():
    outcome = _classify(
        demanded={"python"},
        themer=_Themer(lambda new, existing: RuntimeError("theme down")),
    )

    assert outcome.additions.aliases == {"python": "python"}
    assert outcome.additions.domain_of == {}
    assert any(f.phase == "domain" and f.tokens == ("python",) for f in outcome.failures)


def test_existing_theme_id_is_reused():
    existing = ClusterMap(
        aliases={"kubernetes": "kubernetes"},
        domain_of={"kubernetes": "cloud"},
        domain_label={"cloud": "Cloud"},
    )
    themer = _Themer(
        lambda new, themes: [
            IncrementalDomainGroup(existing_domain_id="cloud", skills=list(new))
        ]
    )

    outcome = _classify(
        demanded={"kubernetes", "terraform"}, existing=existing, themer=themer
    )

    assert outcome.additions.domain_of == {"terraform": "cloud"}
    assert outcome.additions.domain_label == {}


def test_existing_theme_id_without_a_display_label_is_still_reused():
    existing = ClusterMap(
        aliases={"kubernetes": "kubernetes"},
        domain_of={"kubernetes": "cloud"},
    )
    themer = _Themer(
        lambda new, themes: [
            IncrementalDomainGroup(existing_domain_id="cloud", skills=list(new))
        ]
    )

    outcome = _classify(
        demanded={"kubernetes", "terraform"}, existing=existing, themer=themer
    )

    assert outcome.additions.domain_of == {"terraform": "cloud"}


def test_invalid_sizes_are_rejected_at_the_interface():
    with pytest.raises(ValueError, match="batch_size"):
        _classify(demanded={"python"}, batch_size=0)
    with pytest.raises(ValueError, match="concurrency"):
        _classify(demanded={"python"}, concurrency=0)
    with pytest.raises(ValueError, match="category_cap"):
        _classify(demanded={"python"}, category_cap=0)


def test_concurrency_metric_observes_the_semaphore_limit():
    class _DelayedCanonicalizer(_Canonicalizer):
        async def arun(self, prompt):
            await asyncio.sleep(0.02)
            return await super().arun(prompt)

    outcome = _classify(
        demanded={"go", "python", "rust", "typescript"},
        canonicalizer=_DelayedCanonicalizer(),
        batch_size=1,
        concurrency=2,
    )

    assert outcome.metrics.max_in_flight == 2
    assert outcome.metrics.canonical_batches == 4


def test_progress_uses_real_totals_for_each_phase():
    class _Reporter:
        def __init__(self):
            self.begins: list[tuple[int, str]] = []
            self.steps: list[tuple[int, str | None]] = []

        def begin(self, total, label, **extra):
            self.begins.append((total, label))

        def step(self, current, *, label=None, **extra):
            self.steps.append((current, label))

        def checkpoint(self):
            return None

    reporter = _Reporter()
    canonicalizer = _Canonicalizer(
        lambda new, existing: (
            [["k8s", "kube"]] if set(new) == {"k8s", "kube"} else [[new[0]]]
        )
    )

    _classify(
        demanded={"k8s", "kube"},
        canonicalizer=canonicalizer,
        batch_size=1,
        reporter=reporter,
    )

    assert [total for total, _label in reporter.begins] == [2, 1, 1]


def test_prompt_metric_exposes_existing_context_growth():
    small = ClusterMap(aliases={"skill-0": "skill-0"})
    large = ClusterMap(
        aliases={f"skill-{index}": f"skill-{index}" for index in range(50)}
    )

    small_outcome = _classify(demanded={"rust"}, existing=small)
    large_outcome = _classify(demanded={"rust"}, existing=large)

    assert large_outcome.metrics.prompt_bytes > small_outcome.metrics.prompt_bytes


def _map_with_full_category(cap: int) -> ClusterMap:
    domain_of = {}
    domain_label = {}
    category_of = {}
    for index in range(cap):
        domain_id = f"lang-domain-{index}"
        domain_of[f"token{index}"] = domain_id
        domain_label[domain_id] = f"Lang Domain {index}"
        category_of[domain_id] = "languages"
    return ClusterMap(
        aliases={token: token for token in domain_of},
        domain_of=domain_of,
        domain_label=domain_label,
        category_of=category_of,
    )


def test_project_domains_rejects_new_domain_in_full_category():
    result = _project_domains(
        IncrementalSkillDomains(
            domains=[
                IncrementalDomainGroup(
                    new_label="Fresh Langs",
                    new_category="languages",
                    skills=["zig"],
                )
            ]
        ),
        batch={"zig"},
        existing_domain_ids={"lang-domain-0"},
        full_categories={"languages"},
    )

    assert result.assignments == {}
    assert result.failed_tokens == frozenset({"zig"})


def test_project_domains_accepts_reuse_in_full_category():
    result = _project_domains(
        IncrementalSkillDomains(
            domains=[
                IncrementalDomainGroup(
                    existing_domain_id="lang-domain-0", skills=["zig"]
                )
            ]
        ),
        batch={"zig"},
        existing_domain_ids={"lang-domain-0"},
        full_categories={"languages"},
    )

    assert result.assignments["zig"].existing_domain_id == "lang-domain-0"


def test_category_context_lists_all_categories_and_marks_full_ones():
    context = _category_context(_map_with_full_category(3), cap=3)
    by_slug = {entry["slug"]: entry for entry in context}

    assert set(by_slug) == set(SKILL_GROUPS)
    assert by_slug["languages"]["full"] is True
    assert len(by_slug["languages"]["domains"]) == 3
    assert by_slug["ai-ml"]["domains"] == []


def test_soft_target_is_advisory_in_the_incremental_domain_prompt():
    existing = _map_with_full_category(1)
    themer = _Themer()

    _classify(
        demanded={*existing.aliases, "rust"},
        existing=existing,
        themer=themer,
        category_cap=1,
        allow_category_growth=True,
    )

    languages = next(
        category
        for category in themer.calls[0]["categories"]
        if category["slug"] == "languages"
    )
    assert languages["at_soft_target"] is True
    assert languages["full"] is False


def test_concurrent_batches_cannot_overshoot_category_cap():
    existing = _map_with_full_category(1)

    def respond(new, _categories):
        token = new[0]
        return [
            IncrementalDomainGroup(
                new_label=f"Domain {token}",
                new_category="languages",
                skills=[token],
            )
        ]

    outcome = _classify(
        demanded={*existing.aliases, "alpha", "beta"},
        existing=existing,
        themer=_Themer(respond),
        batch_size=1,
        category_cap=2,
    )

    admitted = {token for token in ("alpha", "beta") if token in outcome.additions.domain_of}
    assert admitted == {"alpha"}
    assert any(f.phase == "domain" and f.tokens == ("beta",) for f in outcome.failures)


def test_equal_new_labels_in_different_categories_get_distinct_ids():
    def respond(new, _categories):
        token = new[0]
        category = "languages" if token == "alpha" else "cloud-infra"
        return [
            IncrementalDomainGroup(
                new_label="Platform", new_category=category, skills=[token]
            )
        ]

    outcome = _classify(
        demanded={"alpha", "beta"},
        themer=_Themer(respond),
        batch_size=1,
    )

    assert len(set(outcome.additions.domain_of.values())) == 2
    assert set(outcome.additions.category_of.values()) == {"languages", "cloud-infra"}


def test_retrieval_only_vetoes_a_domain_when_it_is_trustworthy():
    """A candidate slice may narrow the prompt; only a semantic one may forbid.

    Retrieval exists to stop the model reaching across the whole taxonomy on a
    hunch, which is legitimate when candidates are semantic.  Under the lexical
    fallback the slice is close to arbitrary -- measured on a real taxonomy it
    reached barely a third of existing domains -- so vetoing against it rejects
    correct reuse far more often than it catches an invention.
    """

    from resume_agent.taxonomy.classification import _project_domains

    response = IncrementalSkillDomains(
        domains=[
            IncrementalDomainGroup(
                existing_domain_id="backend", confidence="high", skills=["fastapi"]
            )
        ]
    )
    arguments = {
        "batch": {"fastapi"},
        "existing_domain_ids": {"backend", "frontend"},
        "full_categories": set(),
        "allowed_domain_ids": {"frontend"},
    }

    degraded = _project_domains(response, **arguments, enforce_candidates=False)
    assert degraded.assignments["fastapi"].existing_domain_id == "backend"
    assert degraded.failed_tokens == frozenset()

    semantic = _project_domains(response, **arguments, enforce_candidates=True)
    assert semantic.assignments == {}
    assert semantic.failed_tokens == frozenset({"fastapi"})

    # A domain that does not exist is refused either way.
    invented = _project_domains(
        IncrementalSkillDomains(
            domains=[
                IncrementalDomainGroup(
                    existing_domain_id="invented", confidence="high", skills=["fastapi"]
                )
            ]
        ),
        **arguments,
        enforce_candidates=False,
    )
    assert invented.failed_tokens == frozenset({"fastapi"})


def test_a_declined_group_still_records_its_category_for_the_placement_floor():
    """An uncertain judgment is still a judgment about where a skill belongs."""

    from resume_agent.taxonomy.classification import _project_domains

    result = _project_domains(
        IncrementalSkillDomains(
            domains=[
                IncrementalDomainGroup(
                    new_label="Vision Systems",
                    new_category="ai-ml",
                    confidence="low",
                    reason="unsure whether this warrants its own domain",
                    skills=["depth estimation"],
                )
            ],
            not_skills=["ten years of experience"],
        ),
        batch={"depth estimation", "ten years of experience"},
        existing_domain_ids=set(),
        full_categories=set(),
    )

    assert result.assignments == {}
    assert result.fallback_categories == {"depth estimation": "ai-ml"}
    assert result.not_skills == frozenset({"ten years of experience"})
    # A retired token is not a failure to retry.
    assert result.failed_tokens == frozenset({"depth estimation"})
