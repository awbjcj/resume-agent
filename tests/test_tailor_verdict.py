import pytest

from resume_tailor_harness.models.review import ReviewCritique
from resume_tailor_harness.tailor.coverage import COVERAGE_REVIEWER, CoverageCritique
from resume_tailor_harness.tailor.depth import DEPTH_REVIEWER, DepthCritique
from resume_tailor_harness.tailor.review_config import ReviewConfig, ReviewerSpec
from resume_tailor_harness.tailor.verdict import aggregate, failing_gate_names


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
    verdict = aggregate(
        [ReviewCritique(reviewer="provenance", score=0, passed=False)], _config()
    )
    assert verdict.aggregate_score is None
    assert verdict.gate_passed is False
    assert verdict.passed is False


def test_gate_only_roster_scores_none_and_defers_to_the_gate():
    config = ReviewConfig(
        score_threshold=85,
        reviewers=[ReviewerSpec(name="fact-check", gate=True, weight=0)],
    )
    verdict = aggregate(
        [ReviewCritique(reviewer="fact-check", score=100, passed=True)], config
    )
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


def test_new_deterministic_gates_are_registered():
    from resume_tailor_harness.tailor.verdict import DETERMINISTIC_GATES

    assert "skill-naming" in DETERMINISTIC_GATES
    assert "numeric-evidence" in DETERMINISTIC_GATES


def test_a_new_gate_failure_blocks_the_round_and_is_named():
    config = ReviewConfig(reviewers=[ReviewerSpec(name="recruiter", weight=1)])
    critiques = [
        ReviewCritique(reviewer="provenance", score=100, passed=True),
        ReviewCritique(reviewer="numeric-evidence", score=0, passed=False),
        ReviewCritique(reviewer="recruiter", score=90, passed=True),
    ]

    verdict = aggregate(critiques, config)

    assert verdict.gate_passed is False
    assert verdict.passed is False
    assert verdict.aggregate_score == 90
    assert failing_gate_names(critiques, {"recruiter"}) == ["numeric-evidence"]


@pytest.mark.parametrize(
    "spec",
    [
        ReviewerSpec(name=COVERAGE_REVIEWER, weight=1),
        ReviewerSpec(name=COVERAGE_REVIEWER, gate=True, weight=0),
    ],
)
def test_tagged_coverage_is_neither_a_configured_score_nor_gate(spec):
    config = ReviewConfig(score_threshold=85, reviewers=[spec])
    tagged = CoverageCritique(reviewer=COVERAGE_REVIEWER, score=0, passed=False)

    verdict = aggregate([tagged], config)

    assert verdict.aggregate_score is None
    assert verdict.gate_passed is True
    assert verdict.passed is True
    assert failing_gate_names([tagged], {COVERAGE_REVIEWER}) == []
    assert verdict.critiques == [tagged]


def test_normal_same_named_reviewer_still_controls_the_configured_result():
    config = ReviewConfig(
        score_threshold=85,
        reviewers=[ReviewerSpec(name=COVERAGE_REVIEWER, weight=1)],
    )
    tagged = CoverageCritique(reviewer=COVERAGE_REVIEWER, score=0, passed=False)
    normal = ReviewCritique(reviewer=COVERAGE_REVIEWER, score=90, passed=True)

    verdict = aggregate([tagged, normal], config)

    assert verdict.aggregate_score == 90
    assert verdict.gate_passed is True
    assert verdict.passed is True
    assert verdict.critiques == [tagged, normal]


def test_coverage_measurement_does_not_mutate_review_config():
    config = ReviewConfig(
        score_threshold=85,
        reviewers=[
            ReviewerSpec(name=COVERAGE_REVIEWER, gate=True, weight=0),
            ReviewerSpec(name="ats-keyword", weight=1),
        ],
    )
    before = config.model_dump(mode="json")

    aggregate(
        [
            CoverageCritique(reviewer=COVERAGE_REVIEWER, score=0, passed=False),
            ReviewCritique(reviewer="ats-keyword", score=90, passed=True),
        ],
        config,
    )

    assert config.model_dump(mode="json") == before


def test_tagged_depth_measurement_never_shadows_a_same_named_configured_reviewer():
    config = ReviewConfig(
        score_threshold=85,
        reviewers=[ReviewerSpec(name=DEPTH_REVIEWER, gate=True, weight=0)],
    )
    deterministic = DepthCritique(reviewer=DEPTH_REVIEWER, score=0, passed=False)
    configured = ReviewCritique(reviewer=DEPTH_REVIEWER, score=90, passed=True)

    verdict = aggregate([deterministic, configured], config)

    assert verdict.gate_passed is True
    assert verdict.passed is True
    assert failing_gate_names([deterministic, configured], {DEPTH_REVIEWER}) == []
