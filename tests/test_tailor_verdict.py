from resume_agent.models.review import ReviewCritique
from resume_agent.tailor.review_config import ReviewConfig, ReviewerSpec
from resume_agent.tailor.verdict import PanelVerdict, aggregate


def _config(threshold=85):
    return ReviewConfig(
        score_threshold=threshold,
        reviewers=[
            ReviewerSpec(name="fact-check", gate=True, weight=0),
            ReviewerSpec(name="ats-keyword", weight=1),
            ReviewerSpec(name="recruiter", weight=1),
        ],
    )


def test_gate_failure_fails_round_even_with_high_scores():
    critiques = [
        ReviewCritique(reviewer="fact-check", score=0, passed=False),
        ReviewCritique(reviewer="ats-keyword", score=100, passed=True),
        ReviewCritique(reviewer="recruiter", score=100, passed=True),
    ]
    verdict = aggregate(critiques, _config())
    assert verdict.gate_passed is False
    assert verdict.passed is False
    assert verdict.aggregate_score == 100  # weighted score still computed


def test_gate_pass_but_below_threshold_fails():
    critiques = [
        ReviewCritique(reviewer="fact-check", score=100, passed=True),
        ReviewCritique(reviewer="ats-keyword", score=80, passed=True),
        ReviewCritique(reviewer="recruiter", score=80, passed=True),
    ]
    verdict = aggregate(critiques, _config(threshold=85))
    assert verdict.gate_passed is True
    assert verdict.aggregate_score == 80
    assert verdict.passed is False


def test_gate_pass_and_meets_threshold_passes():
    critiques = [
        ReviewCritique(reviewer="fact-check", score=100, passed=True),
        ReviewCritique(reviewer="ats-keyword", score=90, passed=True),
        ReviewCritique(reviewer="recruiter", score=80, passed=True),
    ]
    verdict = aggregate(critiques, _config(threshold=85))
    assert verdict.passed is True
    assert verdict.aggregate_score == 85
