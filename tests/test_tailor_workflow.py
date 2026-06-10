from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import Contact, ProfileFacts
from resume_agent.models.review import Severity
from resume_agent.models.resume import ResumeContent
from resume_agent.models.review import ReviewCritique, ReviewIssue
from resume_agent.tailor.review_config import ReviewConfig, ReviewerSpec
from resume_agent.tailor.workflow import TailorRound, run_tailor_review


class _Result:
    def __init__(self, content):
        self.content = content


class _ContentAgent:
    """Tailor/reviser: always returns a minimal ResumeContent."""

    def run(self, prompt):
        return _Result(ResumeContent(contact=Contact(name="Ada")))


class _FactCheck:
    """Fails the first round, passes afterward (simulating a fix after revise)."""

    def __init__(self):
        self.calls = 0

    def run(self, prompt):
        self.calls += 1
        passed = self.calls > 1
        issues = [] if passed else [ReviewIssue(severity=Severity.blocking, message="unsupported claim")]
        return _Result(ReviewCritique(reviewer="fact-check", score=100 if passed else 0, passed=passed, issues=issues))


class _Good:
    def __init__(self, name):
        self.name = name

    def run(self, prompt):
        return _Result(ReviewCritique(reviewer=self.name, score=95, passed=True))


def test_loop_revises_until_gate_passes():
    config = ReviewConfig(
        max_rounds=3,
        score_threshold=80,
        reviewers=[
            ReviewerSpec(name="fact-check", gate=True, weight=0),
            ReviewerSpec(name="ats-keyword", weight=1),
        ],
    )
    reviewer_agents = {"fact-check": _FactCheck(), "ats-keyword": _Good("ats-keyword")}

    rounds = run_tailor_review(
        jd_text="Backend role",
        criteria=JobCriteria(),
        profile_facts=ProfileFacts(contact=Contact(name="Ada")),
        config=config,
        tailor_agent=_ContentAgent(),
        reviewer_agents=reviewer_agents,
        reviser_agent=_ContentAgent(),
    )

    assert [r.round_num for r in rounds] == [1, 2]
    assert isinstance(rounds[0], TailorRound)
    assert rounds[0].verdict.passed is False
    assert rounds[-1].verdict.passed is True


def test_loop_stops_at_max_rounds_when_never_passing():
    config = ReviewConfig(
        max_rounds=2,
        score_threshold=80,
        reviewers=[ReviewerSpec(name="fact-check", gate=True, weight=0)],
    )

    class _AlwaysFail:
        def run(self, prompt):
            return _Result(ReviewCritique(reviewer="fact-check", score=0, passed=False))

    rounds = run_tailor_review(
        jd_text="x",
        criteria=JobCriteria(),
        profile_facts=ProfileFacts(contact=Contact(name="Ada")),
        config=config,
        tailor_agent=_ContentAgent(),
        reviewer_agents={"fact-check": _AlwaysFail()},
        reviser_agent=_ContentAgent(),
    )
    assert len(rounds) == 2
    assert rounds[-1].verdict.passed is False
