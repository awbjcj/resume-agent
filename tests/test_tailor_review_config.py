from resume_agent.tailor.review_config import ReviewConfig, ReviewerSpec, load_review_config


def test_defaults():
    cfg = ReviewConfig()
    assert cfg.max_rounds == 3
    assert cfg.score_threshold == 85
    assert cfg.reviewers == []


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
    assert cfg.reviewers[0] == ReviewerSpec(name="fact-check", gate=True, weight=0, model_tier="premium")
    assert cfg.reviewers[1].gate is False  # default
