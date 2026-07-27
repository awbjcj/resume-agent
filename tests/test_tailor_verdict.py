from resume_agent.models.review import ReviewCritique
from resume_agent.tailor.review_config import ReviewConfig, ReviewerSpec
from resume_agent.tailor.verdict import aggregate


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


def test_provenance_failure_blocks_gate_even_if_reviewers_pass():
    # Provenance now rides in the critiques list as a deterministic gate, not a bool.
    critiques = [
        ReviewCritique(reviewer="provenance", score=0, passed=False),
        ReviewCritique(reviewer="fact-check", score=100, passed=True),
        ReviewCritique(reviewer="ats-keyword", score=100, passed=True),
        ReviewCritique(reviewer="recruiter", score=100, passed=True),
    ]
    verdict = aggregate(critiques, _config())
    assert verdict.gate_passed is False
    assert verdict.passed is False


def test_no_advisory_critique_means_no_score_not_zero():
    # A provenance failure used to skip the panel, leaving no weighted critique.
    # The mean of nothing is unknown, not 0 - reporting 0 reads as "terrible
    # resume" when it means "never measured".
    verdict = aggregate([ReviewCritique(reviewer="provenance", score=0, passed=False)], _config())
    assert verdict.aggregate_score is None
    assert verdict.gate_passed is False
    assert verdict.passed is False


def test_gate_only_roster_scores_none_and_defers_to_the_gate():
    config = ReviewConfig(
        score_threshold=85,
        reviewers=[ReviewerSpec(name="fact-check", gate=True, weight=0)],
    )
    verdict = aggregate([ReviewCritique(reviewer="fact-check", score=100, passed=True)], config)
    assert verdict.aggregate_score is None
    assert verdict.passed is True  # no advisory bar configured, so the gate decides


def test_passing_provenance_critique_is_a_gate_not_scored():
    # A passing provenance critique gates (it's checked) but never moves the score.
    critiques = [
        ReviewCritique(reviewer="provenance", score=100, passed=True),
        ReviewCritique(reviewer="fact-check", score=100, passed=True),
        ReviewCritique(reviewer="ats-keyword", score=90, passed=True),
        ReviewCritique(reviewer="recruiter", score=80, passed=True),
    ]
    verdict = aggregate(critiques, _config(threshold=85))
    assert verdict.gate_passed is True
    assert verdict.aggregate_score == 85  # provenance's score=100 is excluded
    assert verdict.passed is True
