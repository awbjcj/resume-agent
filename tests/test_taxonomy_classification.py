import asyncio
import json
from types import SimpleNamespace

import pytest

from resume_agent.taxonomy.classification import (
    ClassificationFailure,
    ClassificationMetrics,
    ClassificationOutcome,
    ReconcileError,
    classify_incrementally,
)
from resume_agent.taxonomy.clusters import ClusterMap
from resume_agent.tracking.canonicalize import (
    IncrementalSkillThemes,
    IncrementalThemeGroup,
    SkillClusters,
)


def test_classification_contracts_hold_additions_failures_and_metrics():
    failure = ClassificationFailure(
        phase="canonicalize", tokens=("rust",), message="provider down"
    )
    metrics = ClassificationMetrics(
        canonical_batches=1,
        theme_batches=0,
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
                IncrementalThemeGroup(new_label="Languages", skills=list(new))
            ]
        )
        self.calls: list[dict] = []

    async def arun(self, prompt):
        payload = json.loads(prompt)
        self.calls.append(payload)
        response = self.respond(payload["new"], payload["existing_themes"])
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(content=IncrementalSkillThemes(themes=response))

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
            **kwargs,
        )
    )


def test_warm_complete_map_makes_no_model_calls():
    canonicalizer = _Canonicalizer()
    themer = _Themer()
    existing = ClusterMap(
        aliases={"python": "python"},
        theme_of={"python": "languages"},
        theme_label={"languages": "Languages"},
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
    assert outcome.additions.theme_of == {"k8s": "languages"}
    assert outcome.metrics.canonical_batches == 2


def test_reconcile_preserves_aliases_that_already_target_a_stable_canonical():
    existing = ClusterMap(
        aliases={"kubernetes": "kubernetes"},
        theme_of={"kubernetes": "cloud"},
        theme_label={"cloud": "Cloud"},
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
    assert "rust" not in outcome.additions.theme_of
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


def test_reconcile_failure_is_fatal():
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


def test_existing_unthemed_canonical_is_themed_without_canonical_call():
    canonicalizer = _Canonicalizer()
    existing = ClusterMap(aliases={"python": "python"})

    outcome = _classify(
        demanded={"python"}, existing=existing, canonicalizer=canonicalizer
    )

    assert canonicalizer.calls == []
    assert outcome.additions.theme_of == {"python": "languages"}


def test_failed_theme_batch_keeps_alias_but_not_theme():
    outcome = _classify(
        demanded={"python"},
        themer=_Themer(lambda new, existing: RuntimeError("theme down")),
    )

    assert outcome.additions.aliases == {"python": "python"}
    assert outcome.additions.theme_of == {}
    assert any(f.phase == "theme" and f.tokens == ("python",) for f in outcome.failures)


def test_existing_theme_id_is_reused():
    existing = ClusterMap(
        aliases={"kubernetes": "kubernetes"},
        theme_of={"kubernetes": "cloud"},
        theme_label={"cloud": "Cloud"},
    )
    themer = _Themer(
        lambda new, themes: [
            IncrementalThemeGroup(existing_theme_id="cloud", skills=list(new))
        ]
    )

    outcome = _classify(
        demanded={"kubernetes", "terraform"}, existing=existing, themer=themer
    )

    assert outcome.additions.theme_of == {"terraform": "cloud"}
    assert outcome.additions.theme_label == {}


def test_existing_theme_id_without_a_display_label_is_still_reused():
    existing = ClusterMap(
        aliases={"kubernetes": "kubernetes"},
        theme_of={"kubernetes": "cloud"},
    )
    themer = _Themer(
        lambda new, themes: [
            IncrementalThemeGroup(existing_theme_id="cloud", skills=list(new))
        ]
    )

    outcome = _classify(
        demanded={"kubernetes", "terraform"}, existing=existing, themer=themer
    )

    assert outcome.additions.theme_of == {"terraform": "cloud"}


def test_invalid_sizes_are_rejected_at_the_interface():
    with pytest.raises(ValueError, match="batch_size"):
        _classify(demanded={"python"}, batch_size=0)
    with pytest.raises(ValueError, match="concurrency"):
        _classify(demanded={"python"}, concurrency=0)


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
