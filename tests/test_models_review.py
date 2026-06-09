from resume_agent.models.review import ReviewCritique, ReviewIssue, Severity


def test_blocking_issue_severity():
    issue = ReviewIssue(severity="blocking", message="Claim X not in ProfileFacts")
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
        issues=[ReviewIssue(severity="major", message="Missing keyword: Kubernetes",
                            suggestion="Add it if truthfully supported")],
    )
    restored = ReviewCritique.model_validate(c.model_dump(mode="json"))
    assert restored.issues[0].severity == Severity.major
    assert restored.score == 70
