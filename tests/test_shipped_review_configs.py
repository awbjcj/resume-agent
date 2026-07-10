from resume_agent.setup import preflight
from resume_agent.tailor.review_config import load_review_config


def test_shipped_fast_config_shape():
    # review.yaml is intentionally user-owned/ignored; setup renders this tracked
    # example into the runtime path.
    cfg = load_review_config("config/review.yaml.example")
    assert cfg.merged_advisory is True
    assert cfg.max_rounds == 2
    assert cfg.early_stop_on_regression is True
    assert cfg.tailor_tier == "mid"
    assert cfg.reviser_tier == "mid"
    gates = [reviewer for reviewer in cfg.reviewers if reviewer.gate]
    assert [gate.name for gate in gates] == ["fact-check"]
    assert gates[0].model_tier == "premium"
    assert [reviewer.name for reviewer in cfg.reviewers if not reviewer.gate] == [
        "ats-keyword",
        "recruiter",
        "hiring-manager",
        "concision",
    ]


def test_shipped_deep_config_matches_legacy_roster():
    cfg = load_review_config("config/review_deep.yaml")
    assert cfg.merged_advisory is False
    assert cfg.max_rounds == 3
    assert cfg.tailor_tier == "premium"
    assert cfg.reviser_tier == "premium"
    assert len(cfg.reviewers) == 5


def test_deep_example_registered_with_setup():
    assert "review_deep.yaml.example" in preflight._EXAMPLES
