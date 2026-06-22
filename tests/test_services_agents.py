from resume_agent.services import agents


def test_discovery_bundle_has_three_agents(monkeypatch):
    # Each builder is faked so no SDK/model is constructed (offline).
    monkeypatch.setattr(agents, "build_extract_agent", lambda: "extract")
    monkeypatch.setattr(agents, "build_fit_agent", lambda: "fit")
    monkeypatch.setattr(agents, "build_relevance_agent", lambda: "relevance")
    bundle = agents.build_discovery_bundle()
    assert bundle.extract == "extract"
    assert bundle.fit == "fit"
    assert bundle.relevance == "relevance"


def test_tailor_bundle_builds_one_reviewer_per_spec(monkeypatch):
    class Spec:
        def __init__(self, name):
            self.name = name
            self.model_tier = "cheap"

    class Config:
        reviewers = [Spec("a"), Spec("b")]

    monkeypatch.setattr(agents, "build_tailor_agent", lambda style_guide=None: "tailor")
    monkeypatch.setattr(agents, "build_reviser_agent", lambda style_guide=None: "reviser")
    monkeypatch.setattr(agents, "build_reviewer_agent", lambda name, model, style_guide=None: f"rev:{name}")
    monkeypatch.setattr(agents, "model_for_tier", lambda tier: "model")
    bundle = agents.build_tailor_bundle(Config(), style_guide=None)
    assert bundle.tailor == "tailor"
    assert set(bundle.reviewers) == {"a", "b"}


def test_tailor_bundle_threads_style_guide_into_all_agents(monkeypatch):
    seen = {}
    monkeypatch.setattr(agents, "build_tailor_agent", lambda style_guide=None: seen.setdefault("tailor", style_guide))
    monkeypatch.setattr(agents, "build_reviser_agent", lambda style_guide=None: seen.setdefault("reviser", style_guide))
    monkeypatch.setattr(
        agents, "build_reviewer_agent",
        lambda name, model, style_guide=None: seen.setdefault(f"rev:{name}", style_guide),
    )
    monkeypatch.setattr(agents, "model_for_tier", lambda tier: "model")

    class Spec:
        def __init__(self, name):
            self.name = name
            self.model_tier = "cheap"

    class Config:
        reviewers = [Spec("a")]

    agents.build_tailor_bundle(Config(), style_guide="HOUSE")
    assert seen == {"tailor": "HOUSE", "reviser": "HOUSE", "rev:a": "HOUSE"}
