from resume_tailor_harness.services import agents
from resume_tailor_harness.tailor.review_config import ReviewConfig, ReviewerSpec


class _DummyRunner:
    def run(self, prompt):
        raise NotImplementedError

    async def arun(self, prompt):
        raise NotImplementedError


def test_discovery_bundle_has_all_agents(monkeypatch):
    # Each builder is faked so no SDK/model is constructed (offline).
    monkeypatch.setattr(agents, "build_extract_agent", lambda: "extract")
    monkeypatch.setattr(agents, "build_fit_agent", lambda: "fit")
    monkeypatch.setattr(agents, "build_relevance_agent", lambda: "relevance")
    monkeypatch.setattr(agents, "build_skill_canonicalizer", lambda: "skills")
    monkeypatch.setattr(agents, "build_industry_classifier", lambda: "industry")
    bundle = agents.build_discovery_bundle()
    assert bundle.extract == "extract"
    assert bundle.fit == "fit"
    assert bundle.relevance == "relevance"
    assert bundle.canonicalizer == "skills"
    assert bundle.industry_classifier == "industry"


def test_tailor_bundle_builds_one_reviewer_per_spec(monkeypatch):
    class Spec:
        def __init__(self, name):
            self.name = name
            self.model_tier = "cheap"

    class Config:
        reviewers = [Spec("a"), Spec("b")]

    monkeypatch.setattr(
        agents, "build_tailor_agent", lambda model_id=None, style_guide=None: "tailor"
    )
    monkeypatch.setattr(
        agents, "build_reviser_agent", lambda model_id=None, style_guide=None: "reviser"
    )
    monkeypatch.setattr(
        agents, "build_revision_agent", lambda style_guide=None: "revision"
    )
    monkeypatch.setattr(
        agents,
        "build_reviewer_agent",
        lambda name, model, style_guide=None, score_bands=False: f"rev:{name}",
    )
    monkeypatch.setattr(agents, "model_for_tier", lambda tier: "model")
    bundle = agents.build_tailor_bundle(Config(), style_guide=None)
    assert bundle.tailor == "tailor"
    assert bundle.revision == "revision"
    assert set(bundle.reviewers) == {"a", "b"}


def test_tailor_bundle_threads_style_guide_into_all_agents(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        agents,
        "build_tailor_agent",
        lambda model_id=None, style_guide=None: seen.setdefault("tailor", style_guide),
    )
    monkeypatch.setattr(
        agents,
        "build_reviser_agent",
        lambda model_id=None, style_guide=None: seen.setdefault("reviser", style_guide),
    )
    monkeypatch.setattr(
        agents,
        "build_revision_agent",
        lambda style_guide=None: seen.setdefault("revision", style_guide),
    )
    monkeypatch.setattr(
        agents,
        "build_reviewer_agent",
        lambda name, model, style_guide=None, score_bands=False: seen.setdefault(
            f"rev:{name}", style_guide
        ),
    )
    monkeypatch.setattr(agents, "model_for_tier", lambda tier: "model")

    class Spec:
        def __init__(self, name):
            self.name = name
            self.model_tier = "cheap"

    class Config:
        reviewers = [Spec("a")]

    agents.build_tailor_bundle(Config(), style_guide="HOUSE")
    assert seen == {
        "tailor": "HOUSE",
        "reviser": "HOUSE",
        "revision": "HOUSE",
        "rev:a": "HOUSE",
    }


def test_tailor_bundle_builds_evidence_portfolio_only_when_enabled(monkeypatch):
    monkeypatch.setattr(agents, "build_tailor_agent", lambda **kwargs: object())
    monkeypatch.setattr(agents, "build_reviser_agent", lambda **kwargs: object())
    monkeypatch.setattr(agents, "build_revision_agent", lambda **kwargs: object())
    monkeypatch.setattr(
        agents, "build_reviewer_agent", lambda *args, **kwargs: object()
    )
    sentinel = object()
    monkeypatch.setattr(
        agents, "build_evidence_portfolio_agent", lambda **kwargs: sentinel
    )

    enabled = ReviewConfig(match_plan_enabled=True)
    disabled = ReviewConfig(match_plan_enabled=False)

    assert agents.build_tailor_bundle(enabled).match_plan is sentinel
    assert agents.build_tailor_bundle(enabled).evidence_portfolio is sentinel
    assert agents.build_tailor_bundle(disabled).match_plan is None
    assert agents.build_tailor_bundle(disabled).evidence_portfolio is None


def test_tailor_bundle_threads_score_band_opt_in(monkeypatch):
    seen = []
    monkeypatch.setattr(agents, "build_tailor_agent", lambda **kwargs: object())
    monkeypatch.setattr(agents, "build_reviser_agent", lambda **kwargs: object())
    monkeypatch.setattr(agents, "build_revision_agent", lambda **kwargs: object())
    monkeypatch.setattr(agents, "build_match_plan_agent", lambda **kwargs: object())
    monkeypatch.setattr(
        agents,
        "build_reviewer_agent",
        lambda *args, **kwargs: (
            seen.append(kwargs.get("score_bands", False)) or object()
        ),
    )

    agents.build_tailor_bundle(
        ReviewConfig(reviewers=[ReviewerSpec(name="recruiter", score_bands=True)])
    )

    assert seen == [True]


def test_tailor_bundle_match_plan_defaults_none():
    bundle = agents.TailorBundle(
        tailor=_DummyRunner(),
        reviser=_DummyRunner(),
        reviewers={},
        revision=_DummyRunner(),
    )
    assert bundle.match_plan is None


def test_tailor_bundle_threads_writer_tiers(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        agents,
        "build_tailor_agent",
        lambda model_id=None, style_guide=None: seen.setdefault("tailor", model_id),
    )
    monkeypatch.setattr(
        agents,
        "build_reviser_agent",
        lambda model_id=None, style_guide=None: seen.setdefault("reviser", model_id),
    )
    monkeypatch.setattr(
        agents, "build_revision_agent", lambda style_guide=None: "revision"
    )
    monkeypatch.setattr(
        agents,
        "build_reviewer_agent",
        lambda name, model, style_guide=None, score_bands=False: f"review:{name}",
    )
    monkeypatch.setattr(agents, "model_for_tier", lambda tier: f"model:{tier}")

    config = ReviewConfig(
        tailor_tier="mid",
        reviser_tier="cheap",
        reviewers=[ReviewerSpec(name="ats-keyword")],
    )
    agents.build_tailor_bundle(config)

    assert seen == {"tailor": "model:mid", "reviser": "model:cheap"}


def test_tailor_bundle_builds_one_merged_advisory_agent(monkeypatch):
    from resume_tailor_harness.tailor.panel import MERGED_ADVISORY

    monkeypatch.setattr(agents, "build_tailor_agent", lambda **kwargs: object())
    monkeypatch.setattr(agents, "build_reviser_agent", lambda **kwargs: object())
    monkeypatch.setattr(agents, "build_revision_agent", lambda **kwargs: object())
    monkeypatch.setattr(
        agents, "build_reviewer_agent", lambda name, *args, **kwargs: name
    )
    monkeypatch.setattr(
        agents,
        "build_merged_advisory_agent",
        lambda names, *args, **kwargs: tuple(names),
    )

    bundle = agents.build_tailor_bundle(
        ReviewConfig(
            merged_advisory=True,
            reviewers=[
                ReviewerSpec(name="fact-check", gate=True),
                ReviewerSpec(name="ats-keyword"),
                ReviewerSpec(name="recruiter"),
            ],
        )
    )

    assert set(bundle.reviewers) == {"fact-check", MERGED_ADVISORY}
    assert bundle.reviewers[MERGED_ADVISORY] == ("ats-keyword", "recruiter")
