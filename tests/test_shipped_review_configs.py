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
    assert cfg.evidence_portfolio_enabled is False
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
    assert cfg.evidence_portfolio_enabled is True
    assert len(cfg.reviewers) == 5


def test_deep_example_registered_with_setup():
    assert "review_deep.yaml.example" in preflight._EXAMPLES


def test_every_advisory_reviewer_shares_one_scoring_scale():
    # Five reviewers scoring on five private scales were being averaged and
    # compared to one fixed threshold. score_bands gives them a common rubric.
    for path in ("config/review.yaml.example", "config/review_deep.yaml.example"):
        cfg = load_review_config(path)
        advisory = [reviewer for reviewer in cfg.reviewers if not reviewer.gate]
        assert advisory, path
        assert all(reviewer.score_bands for reviewer in advisory), path


def test_fact_check_gate_keeps_its_own_scoring_rule():
    # The gate fixes score=100 on pass; a shared band rubric would fight that.
    for path in ("config/review.yaml.example", "config/review_deep.yaml.example"):
        cfg = load_review_config(path)
        gates = [reviewer for reviewer in cfg.reviewers if reviewer.gate]
        assert all(not gate.score_bands for gate in gates), path


def test_both_shipped_rosters_stop_on_regression():
    for path in ("config/review.yaml.example", "config/review_deep.yaml.example"):
        assert load_review_config(path).early_stop_on_regression is True, path
