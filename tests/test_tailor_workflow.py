import pytest

from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import Bullet, Contact, Experience, ProfileFacts
from resume_agent.models.review import Severity
from resume_agent.models.resume import ResumeContent, TailoredBullet, TailoredExperience
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

    async def arun(self, prompt):
        return self.run(prompt)


class _FactCheck:
    """Fails the first round, passes afterward (simulating a fix after revise)."""

    def __init__(self):
        self.calls = 0

    def run(self, prompt):
        self.calls += 1
        passed = self.calls > 1
        issues = [] if passed else [ReviewIssue(severity=Severity.blocking, message="unsupported claim")]
        return _Result(ReviewCritique(reviewer="fact-check", score=100 if passed else 0, passed=passed, issues=issues))

    async def arun(self, prompt):
        return self.run(prompt)


class _Good:
    def __init__(self, name):
        self.name = name

    def run(self, prompt):
        return _Result(ReviewCritique(reviewer=self.name, score=95, passed=True))

    async def arun(self, prompt):
        return self.run(prompt)


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


def test_rounds_record_stage_seconds_on_the_round_the_content_enters():
    config = ReviewConfig(
        max_rounds=3,
        score_threshold=80,
        reviewers=[
            ReviewerSpec(name="fact-check", gate=True, weight=0),
            ReviewerSpec(name="ats-keyword"),
        ],
    )

    rounds = run_tailor_review(
        jd_text="Backend role",
        criteria=JobCriteria(),
        profile_facts=ProfileFacts(contact=Contact(name="Ada")),
        config=config,
        tailor_agent=_ContentAgent(),
        reviewer_agents={
            "fact-check": _FactCheck(),
            "ats-keyword": _Good("ats-keyword"),
        },
        reviser_agent=_ContentAgent(),
    )

    assert rounds[0].stage_seconds.keys() >= {"draft", "panel"}
    assert rounds[1].stage_seconds.keys() >= {"revise", "panel"}
    assert all(seconds >= 0 for round_ in rounds for seconds in round_.stage_seconds.values())


def test_arun_tailor_review_passes_with_async_agents():
    import asyncio

    from resume_agent.tailor.workflow import arun_tailor_review

    class _Content:
        def run(self, prompt):
            raise NotImplementedError

        async def arun(self, prompt):
            return _Result(ResumeContent(contact=Contact(name="Ada")))

    class _FactCheckAsync:
        def run(self, prompt):
            raise NotImplementedError

        async def arun(self, prompt):
            return _Result(ReviewCritique(reviewer="fact-check", score=100, passed=True))

    config = ReviewConfig(
        max_rounds=1,
        score_threshold=50,
        reviewers=[ReviewerSpec(name="fact-check", gate=True, weight=0)],
    )

    async def go():
        return await arun_tailor_review(
            "jd",
            JobCriteria(),
            ProfileFacts(contact=Contact(name="Ada")),
            config,
            _Content(),
            {"fact-check": _FactCheckAsync()},
            _Content(),
            sem=asyncio.Semaphore(8),
        )

    rounds = asyncio.run(go())
    assert len(rounds) == 1
    assert rounds[0].round_num == 1
    assert rounds[0].stage_seconds.keys() >= {"draft", "panel"}


def test_loop_stops_at_max_rounds_when_never_passing():
    config = ReviewConfig(
        max_rounds=2,
        score_threshold=80,
        reviewers=[ReviewerSpec(name="fact-check", gate=True, weight=0)],
    )

    class _AlwaysFail:
        def run(self, prompt):
            return _Result(ReviewCritique(reviewer="fact-check", score=0, passed=False))

        async def arun(self, prompt):
            return self.run(prompt)

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


def test_broken_provenance_short_circuits_panel():
    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[
            Experience(
                id="e1",
                company="AE",
                title="Eng",
                bullets=[Bullet(id="b1", text="X")],
            )
        ],
    )

    class _BadTailor:
        def run(self, prompt):
            return _Result(
                ResumeContent(
                    contact=Contact(name="Ada"),
                    experience=[
                        TailoredExperience(
                            company="AE",
                            title="Eng",
                            provenance="e1",
                            bullets=[TailoredBullet(text="X", provenance="ghost")],
                        )
                    ],
                )
            )

        async def arun(self, prompt):
            return self.run(prompt)

    class _ExplodingReviewer:
        def run(self, prompt):
            raise AssertionError("panel should be skipped when provenance is broken")

        async def arun(self, prompt):
            return self.run(prompt)

    config = ReviewConfig(
        max_rounds=1,
        score_threshold=1,
        reviewers=[ReviewerSpec(name="fact-check", gate=True, weight=0)],
    )

    rounds = run_tailor_review(
        jd_text="role",
        criteria=JobCriteria(),
        profile_facts=facts,
        config=config,
        tailor_agent=_BadTailor(),
        reviewer_agents={"fact-check": _ExplodingReviewer()},
        reviser_agent=_BadTailor(),
    )

    assert len(rounds) == 1
    assert rounds[0].verdict.gate_passed is False
    assert rounds[0].verdict.critiques[0].reviewer == "provenance"


def test_match_plan_runs_only_when_enabled_and_is_normalized():
    from resume_agent.models.match_plan import MatchPlan, MatchPlanRequirement

    class _CapturingTailor(_ContentAgent):
        def __init__(self):
            self.prompts = []

        def run(self, prompt):
            self.prompts.append(prompt)
            return super().run(prompt)

    class _Planner:
        def __init__(self):
            self.calls = 0

        def run(self, prompt):
            self.calls += 1
            return _Result(
                MatchPlan(
                    requirements=[
                        MatchPlanRequirement(
                            jd_requirement="Python",
                            supporting_fact_ids=["missing"],
                            emphasis="untrusted note",
                        )
                    ]
                )
            )

        async def arun(self, prompt):
            return self.run(prompt)

    config = ReviewConfig(
        max_rounds=1,
        score_threshold=80,
        match_plan_enabled=True,
        reviewers=[ReviewerSpec(name="ats-keyword", weight=1)],
    )
    tailor_agent = _CapturingTailor()
    planner = _Planner()

    run_tailor_review(
        "Backend",
        JobCriteria(),
        ProfileFacts(contact=Contact(name="Ada")),
        config,
        tailor_agent,
        {"ats-keyword": _Good("ats-keyword")},
        _ContentAgent(),
        match_plan_agent=planner,
    )

    assert planner.calls == 1
    assert "MATCH PLAN" in tailor_agent.prompts[0]
    assert '"gap":true' in tailor_agent.prompts[0]
    assert "missing" not in tailor_agent.prompts[0]


def test_match_plan_enabled_requires_agent():
    config = ReviewConfig(max_rounds=1, match_plan_enabled=True)
    with pytest.raises(ValueError, match="requires a match-plan agent"):
        run_tailor_review(
            "Backend",
            JobCriteria(),
            ProfileFacts(contact=Contact(name="Ada")),
            config,
            _ContentAgent(),
            {},
            _ContentAgent(),
        )


def test_early_stop_halts_after_clean_score_regression():
    class _Scores:
        def __init__(self):
            self.scores = iter([80, 70, 60])

        def run(self, prompt):
            score = next(self.scores)
            return _Result(
                ReviewCritique(
                    reviewer="ats-keyword", score=score, passed=False
                )
            )

        async def arun(self, prompt):
            return self.run(prompt)

    config = ReviewConfig(
        max_rounds=3,
        score_threshold=85,
        early_stop_on_regression=True,
        reviewers=[ReviewerSpec(name="ats-keyword", weight=1)],
    )

    rounds = run_tailor_review(
        "jd",
        JobCriteria(),
        ProfileFacts(contact=Contact(name="Ada")),
        config,
        _ContentAgent(),
        {"ats-keyword": _Scores()},
        _ContentAgent(),
    )

    assert len(rounds) == 2


def test_early_stop_does_not_halt_before_any_clean_round():
    class _Gate:
        def __init__(self):
            self.passed = iter([False, False, True])

        def run(self, prompt):
            passed = next(self.passed)
            return _Result(
                ReviewCritique(
                    reviewer="fact-check",
                    score=100 if passed else 0,
                    passed=passed,
                )
            )

        async def arun(self, prompt):
            return self.run(prompt)

    config = ReviewConfig(
        max_rounds=3,
        score_threshold=101,
        early_stop_on_regression=True,
        reviewers=[ReviewerSpec(name="fact-check", gate=True, weight=0)],
    )

    rounds = run_tailor_review(
        "jd",
        JobCriteria(),
        ProfileFacts(contact=Contact(name="Ada")),
        config,
        _ContentAgent(),
        {"fact-check": _Gate()},
        _ContentAgent(),
    )

    assert len(rounds) == 3
