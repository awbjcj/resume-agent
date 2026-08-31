import pytest
from pydantic import ValidationError

from resume_tailor_harness.models.review import ReviewCritique, ReviewIssue, Severity


def test_blocking_issue_severity():
    issue = ReviewIssue(
        severity=Severity.blocking, message="Claim X not in ProfileFacts"
    )
    assert issue.severity == Severity.blocking


def test_critique_defaults_to_no_issues():
    c = ReviewCritique(reviewer="fact-check", score=100, passed=True)
    assert c.issues == []
    assert c.passed is True


def test_critique_round_trips():
    c = ReviewCritique(
        reviewer="ats-keyword",
        score=70,
        passed=False,
        issues=[
            ReviewIssue(
                severity=Severity.major,
                message="Missing keyword: Kubernetes",
                suggestion="Add it if truthfully supported",
            )
        ],
        suggestions=[
            "Only add Kubernetes if a ProfileFacts skill or project supports it"
        ],
    )
    restored = ReviewCritique.model_validate(c.model_dump(mode="json"))
    assert restored.issues[0].severity == Severity.major
    assert restored.score == 70
    assert restored.suggestions == [
        "Only add Kubernetes if a ProfileFacts skill or project supports it"
    ]


def test_critique_rejects_out_of_range_score():
    with pytest.raises(ValidationError):
        ReviewCritique(reviewer="recruiter", score=-1, passed=False)
