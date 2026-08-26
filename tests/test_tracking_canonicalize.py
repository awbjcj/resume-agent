from types import SimpleNamespace

import resume_agent.tracking.canonicalize as canonicalize_module

from resume_agent.tracking.canonicalize import (
    build_classification_agents,
    IncrementalDomainGroup,
    IncrementalSkillDomains,
    SkillClusters,
    build_incremental_canonicalizer_agent,
    build_incremental_themer_agent,
    build_skill_canonicalizer,
    clusters_to_mapping,
)


def test_classification_agent_policy_builds_every_phase_runner(monkeypatch):
    monkeypatch.setattr(
        canonicalize_module, "build_incremental_canonicalizer_agent", lambda: "canon"
    )
    monkeypatch.setattr(
        canonicalize_module, "build_incremental_themer_agent", lambda: "theme"
    )
    monkeypatch.setattr(
        canonicalize_module, "build_escalation_themer_agent", lambda: "escalate"
    )

    agents = build_classification_agents()

    assert agents.canonicalizer == "canon"
    assert agents.themer == "theme"
    assert agents.escalation_themer == "escalate"


def test_clusters_to_mapping_uses_first_member_as_canonical():
    mapping = clusters_to_mapping([["kubernetes", "k8s"]], {"kubernetes", "k8s", "python"})

    assert mapping == {
        "kubernetes": "kubernetes",
        "k8s": "kubernetes",
        "python": "python",
    }


def test_clusters_to_mapping_projects_rewritten_canonical_onto_input():
    # The model rewrote the canonical ("CI/CD" instead of the input "ci cd").
    # The mapping value must stay within the authoritative input token set.
    mapping = clusters_to_mapping(
        [["CI/CD", "ci cd", "continuous integration"]],
        {"ci cd", "continuous integration", "python"},
    )

    assert mapping == {
        "ci cd": "ci cd",
        "continuous integration": "ci cd",
        "python": "python",
    }


def test_clusters_to_mapping_ignores_invented_tokens():
    # A cluster member the model invented (not an input token) is dropped, not
    # promoted to a canonical that would escape the input set.
    mapping = clusters_to_mapping(
        [["kubernetes", "k8s", "container orchestration"]],
        {"kubernetes", "k8s"},
    )

    assert mapping == {"kubernetes": "kubernetes", "k8s": "kubernetes"}


def test_clusters_to_mapping_flattens_overlapping_clusters_to_first_canonical():
    mapping = clusters_to_mapping(
        [["kubernetes", "k8s"], ["k8s", "kube"]],
        {"kubernetes", "k8s", "kube"},
    )

    assert mapping == {
        "kubernetes": "kubernetes",
        "k8s": "kubernetes",
        "kube": "kubernetes",
    }


class _FakeResult:
    def __init__(self, content):
        self.content = content


class _FakeRunner:
    def __init__(self, clusters):
        self._clusters = clusters

    def run(self, prompt):
        return _FakeResult(SkillClusters(clusters=self._clusters))

    async def arun(self, prompt):
        return self.run(prompt)


def test_canonicalizer_collapses_synonyms_with_a_fake_agent():
    canon = build_skill_canonicalizer(agent=_FakeRunner([["kubernetes", "k8s"]]))

    assert canon({"kubernetes", "k8s", "python"}) == {
        "kubernetes": "kubernetes",
        "k8s": "kubernetes",
        "python": "python",
    }


def test_canonicalizer_keeps_values_within_input_when_model_rewrites():
    # End-to-end: the model rewrites the canonical case and invents "py"; the
    # Alias values stay terminal input tokens at the model-output seam.
    canon = build_skill_canonicalizer(agent=_FakeRunner([["Python", "python", "py"]]))

    assert canon({"python"}) == {"python": "python"}


def test_canonicalizer_short_circuits_on_empty():
    canon = build_skill_canonicalizer(agent=_FakeRunner([]))

    assert canon(set()) == {}


def _capture_default_model(monkeypatch, factory):
    captured = {}
    settings = SimpleNamespace(cheap_model="cheap", mid_model="mid", premium_model="premium")
    monkeypatch.setattr(canonicalize_module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        canonicalize_module,
        "build_model",
        lambda model_id, **kwargs: captured.setdefault("model_id", model_id),
    )
    monkeypatch.setattr(
        canonicalize_module, "Agent", lambda **kwargs: SimpleNamespace(**kwargs)
    )
    monkeypatch.setattr(canonicalize_module, "AgentRunner", lambda agent: agent)
    monkeypatch.setattr(
        canonicalize_module, "use_json_mode_for", lambda model, schema=None: False
    )

    factory()
    return captured["model_id"]


def test_default_canonicalizer_uses_premium_model(monkeypatch):
    assert _capture_default_model(monkeypatch, canonicalize_module._default_agent) == "premium"


def test_default_themer_uses_mid_model(monkeypatch):
    assert _capture_default_model(monkeypatch, canonicalize_module._default_themer_agent) == "mid"


def test_incremental_domain_schema_distinguishes_existing_id_from_new_domain():
    content = IncrementalSkillDomains(
        domains=[
            IncrementalDomainGroup(existing_domain_id="cloud", skills=["kubernetes"]),
            IncrementalDomainGroup(
                new_label="Languages",
                new_category="languages",
                skills=["python"],
            ),
        ]
    )

    assert content.domains[0].existing_domain_id == "cloud"
    assert content.domains[1].new_category == "languages"


def test_incremental_builders_use_expected_models_and_retry_policy(monkeypatch):
    captured: list[dict] = []
    settings = SimpleNamespace(
        cheap_model="cheap",
        mid_model="mid",
        premium_model="premium",
        llm_retries=3,
        llm_retry_delay=2,
    )
    monkeypatch.setattr(canonicalize_module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        canonicalize_module, "build_model", lambda model_id, **kwargs: model_id
    )
    monkeypatch.setattr(
        canonicalize_module, "use_json_mode_for", lambda model, schema=None: False
    )
    monkeypatch.setattr(canonicalize_module, "retry_kwargs", lambda: {"retries": 3})
    monkeypatch.setattr(
        canonicalize_module,
        "Agent",
        lambda **kwargs: captured.append(kwargs) or SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(canonicalize_module, "AgentRunner", lambda agent: agent)

    build_incremental_canonicalizer_agent()
    build_incremental_themer_agent()

    assert [entry["model"] for entry in captured] == ["premium", "mid"]
    assert captured[0]["output_schema"] is SkillClusters
    assert captured[1]["output_schema"] is IncrementalSkillDomains
    assert all(entry["retries"] == 3 for entry in captured)
