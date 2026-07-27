from resume_agent.models.profile import Contact, ProfileFacts
from resume_agent.models.resume import ResumeContent
from resume_agent.models.review import ReviewCritique, ReviewIssue, Severity
from resume_agent.tailor.tailoring import compose_revise_input


def _critique() -> ReviewCritique:
    return ReviewCritique(
        reviewer="ats-keyword",
        score=70,
        passed=False,
        issues=[
            ReviewIssue(
                severity=Severity.minor,
                message="tighten summary",
                location="summary",
            ),
            ReviewIssue(
                severity=Severity.blocking,
                message="unsupported metric",
                location="experience[0].bullet[1]",
            ),
            ReviewIssue(
                severity=Severity.major,
                message="missing keyword",
                location="skills",
            ),
        ],
        suggestions=["mention REST when supported"],
    )


def test_revise_input_orders_severities_and_keeps_locations():
    text = compose_revise_input(
        ResumeContent(contact=Contact(name="Ada")),
        [_critique()],
        ProfileFacts(contact=Contact(name="Ada")),
        "Backend role",
    )

    assert text.index("unsupported metric") < text.index("missing keyword")
    assert text.index("missing keyword") < text.index("tighten summary")
    assert "experience[0].bullet[1]" in text
    assert all(label in text for label in ("BLOCKING", "MAJOR", "MINOR"))


def test_revise_input_preserves_unimplicated_and_handles_no_issues():
    facts = ProfileFacts(contact=Contact(name="Ada"))
    content = ResumeContent(contact=Contact(name="Ada"))
    text = compose_revise_input(content, [_critique()], facts, "Backend role")
    clean = compose_revise_input(
        content,
        [ReviewCritique(reviewer="recruiter", score=95, passed=True)],
        facts,
        "Backend role",
    )

    assert "byte-for-byte" in text
    assert "(none)" in clean
