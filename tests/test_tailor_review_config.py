import pytest
from pydantic import ValidationError

from resume_agent.tailor.review_config import (
    ReviewConfig,
    ReviewerSpec,
    load_review_config,
)


def test_defaults():
    cfg = ReviewConfig()
    assert cfg.max_rounds == 3
    assert cfg.score_threshold == 85
    assert cfg.reviewers == []
    assert cfg.style_guide_path == "config/style_guide.md"


def test_load_from_yaml(tmp_path):
    f = tmp_path / "review.yaml"
    f.write_text(
        "max_rounds: 2\nscore_threshold: 80\nreviewers:\n"
        "  - name: fact-check\n    gate: true\n    weight: 0\n    model_tier: premium\n"
        "  - name: ats-keyword\n    weight: 1\n    model_tier: mid\n",
        encoding="utf-8",
    )
    cfg = load_review_config(f)
    assert cfg.max_rounds == 2
    assert len(cfg.reviewers) == 2
    assert cfg.reviewers[0] == ReviewerSpec(
        name="fact-check", gate=True, weight=0, model_tier="premium"
    )
    assert cfg.reviewers[1].gate is False  # default


def test_style_guide_path_from_yaml(tmp_path):
    f = tmp_path / "review.yaml"
    f.write_text("style_guide_path: config/custom_style.md\n", encoding="utf-8")

    assert load_review_config(f).style_guide_path == "config/custom_style.md"


def test_fast_mode_fields_default_to_legacy_behavior():
    cfg = ReviewConfig()
    assert cfg.merged_advisory is False
    assert cfg.tailor_tier == "premium"
    assert cfg.reviser_tier == "premium"
    assert cfg.evidence_portfolio_enabled is False


def test_evidence_portfolio_flag_accepts_the_one_release_legacy_alias():
    canonical = ReviewConfig(evidence_portfolio_enabled=True)
    legacy = ReviewConfig(match_plan_enabled=True)

    assert canonical.evidence_portfolio_enabled is True
    assert canonical.match_plan_enabled is True
    assert legacy.evidence_portfolio_enabled is True
    assert legacy.match_plan_enabled is True


def test_evidence_portfolio_flag_rejects_conflicting_alias_values():
    with pytest.raises(ValidationError, match="conflicts with legacy"):
        ReviewConfig(evidence_portfolio_enabled=True, match_plan_enabled=False)


def test_fast_mode_fields_load_from_yaml(tmp_path):
    path = tmp_path / "review.yaml"
    path.write_text(
        "merged_advisory: true\ntailor_tier: mid\nreviser_tier: cheap\n",
        encoding="utf-8",
    )

    cfg = load_review_config(path)

    assert cfg.merged_advisory is True
    assert cfg.tailor_tier == "mid"
    assert cfg.reviser_tier == "cheap"


def test_fast_mode_rejects_unknown_writer_tier():
    with pytest.raises(ValidationError):
        ReviewConfig(tailor_tier="typo")  # type: ignore[arg-type]


@pytest.mark.parametrize("name", ["provenance", "skill-naming", "numeric-evidence"])
def test_deterministic_gate_names_are_reserved_from_configured_reviewers(name):
    with pytest.raises(ValidationError, match=name):
        ReviewConfig(reviewers=[ReviewerSpec(name=name)])


def test_must_have_coverage_remains_a_valid_configured_reviewer_name():
    config = ReviewConfig(
        reviewers=[ReviewerSpec(name="must-have-coverage", gate=True, weight=0)]
    )

    assert config.reviewers[0].name == "must-have-coverage"
