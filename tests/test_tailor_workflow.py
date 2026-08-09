from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import Bullet, Contact, Experience, ProfileFacts
from resume_agent.models.review import Severity
from resume_agent.models.resume import ResumeContent, TailoredBullet, TailoredExperience
from resume_agent.models.review import ReviewCritique, ReviewIssue
from resume_agent.tailor.review_config import ReviewConfig, ReviewerSpec
from resume_agent.tailor.verdict import PanelVerdict, aggregate
from resume_agent.tailor.workflow import (
    TailorRound,
    _has_regressed,
    _is_citation_slip,
    run_tailor_review,
)


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
        issues = (
            []
            if passed
            else [ReviewIssue(severity=Severity.blocking, message="unsupported claim")]
        )
        return _Result(
            ReviewCritique(
                reviewer="fact-check",
                score=100 if passed else 0,
                passed=passed,
                issues=issues,
            )
        )

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
    assert all(
        seconds >= 0 for round_ in rounds for seconds in round_.stage_seconds.values()
    )


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
            return _Result(
                ReviewCritique(reviewer="fact-check", score=100, passed=True)
            )

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
    assert {
        "provenance",
        "skill-naming",
        "numeric-evidence",
    } <= {critique.reviewer for critique in rounds[0].verdict.critiques}


def test_arun_evidence_portfolio_runs_once_and_reaches_the_writer():
    import asyncio

    from resume_agent.models.evidence_portfolio import (
        EvidencePortfolio,
        PortfolioSelection,
    )
    from resume_agent.tailor.workflow import arun_tailor_review

    class _AsyncWriter:
        def __init__(self):
            self.prompt = ""

        def run(self, prompt):
            raise NotImplementedError

        async def arun(self, prompt):
            self.prompt = prompt
            return _Result(ResumeContent(contact=Contact(name="Ada")))

    class _AsyncPlanner:
        def __init__(self):
            self.calls = 0

        def run(self, prompt):
            raise NotImplementedError

        async def arun(self, prompt):
            self.calls += 1
            return _Result(
                EvidencePortfolio(
                    selections=[
                        PortfolioSelection(
                            owner_id="e1",
                            owner_kind="experience",
                            selected_fact_ids=["b1"],
                            rank=1,
                            bullet_budget=1,
                        )
                    ]
                )
            )

    writer = _AsyncWriter()
    planner = _AsyncPlanner()

    async def go():
        return await arun_tailor_review(
            "Python role",
            JobCriteria(must_have_skills=["Python"]),
            _slip_facts(),
            ReviewConfig(max_rounds=1, evidence_portfolio_enabled=True),
            writer,
            {},
            writer,
            evidence_portfolio_agent=planner,
            sem=asyncio.Semaphore(2),
        )

    rounds = asyncio.run(go())

    assert planner.calls == 1
    assert rounds[0].evidence_portfolio is not None
    assert "EVIDENCE PORTFOLIO" in writer.prompt


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


def test_broken_provenance_still_runs_the_panel():
    # The panel used to be skipped when provenance failed. That saved one
    # advisory call and cost two things: the round reported no score at all, and
    # the reviser was handed a citation complaint with zero quality feedback.
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

    config = ReviewConfig(
        max_rounds=1,
        score_threshold=1,
        provenance_retry_budget=0,  # isolate: this test is about the panel running
        reviewers=[
            ReviewerSpec(name="fact-check", gate=True, weight=0),
            ReviewerSpec(name="ats-keyword", weight=1),
        ],
    )

    rounds = run_tailor_review(
        jd_text="role",
        criteria=JobCriteria(),
        profile_facts=facts,
        config=config,
        tailor_agent=_BadTailor(),
        reviewer_agents={
            "fact-check": _Good("fact-check"),
            "ats-keyword": _Good("ats-keyword"),
        },
        reviser_agent=_BadTailor(),
    )

    verdict = rounds[0].verdict
    assert len(rounds) == 1
    assert verdict.critiques[0].reviewer == "provenance"
    # The advisory panel ran, so the score is a real measurement...
    assert [c.reviewer for c in verdict.critiques] == [
        "provenance",
        "skill-naming",
        "numeric-evidence",
        "fact-check",
        "ats-keyword",
    ]
    assert verdict.aggregate_score == 95
    # ...and the gate still blocks the round. Fact-lock is unchanged.
    assert verdict.gate_passed is False
    assert verdict.passed is False


def test_every_round_carries_the_deterministic_critiques():
    config = ReviewConfig(
        max_rounds=1,
        score_threshold=80,
        reviewers=[ReviewerSpec(name="ats-keyword", weight=1)],
    )
    rounds = run_tailor_review(
        jd_text="Backend role",
        criteria=JobCriteria(),
        profile_facts=ProfileFacts(contact=Contact(name="Ada")),
        config=config,
        tailor_agent=_ContentAgent(),
        reviewer_agents={"ats-keyword": _Good("ats-keyword")},
        reviser_agent=_ContentAgent(),
    )

    names = {critique.reviewer for critique in rounds[0].verdict.critiques}
    assert {"provenance", "skill-naming", "numeric-evidence"} <= names


def test_a_new_gate_failure_is_not_granted_the_provenance_free_retry():
    """A citation slip is provenance ONLY; a numeric failure is a real round."""
    config = ReviewConfig(reviewers=[ReviewerSpec(name="recruiter", weight=1)])
    verdict = aggregate(
        [
            ReviewCritique(reviewer="provenance", score=0, passed=False),
            ReviewCritique(reviewer="numeric-evidence", score=0, passed=False),
            ReviewCritique(reviewer="recruiter", score=70, passed=True),
        ],
        config,
    )

    assert _is_citation_slip(verdict, config) is False


def test_evidence_portfolio_runs_once_and_is_normalized():
    from resume_agent.models.evidence_portfolio import (
        EvidencePortfolio,
        PortfolioSelection,
    )
    from resume_agent.models.profile import Bullet, Experience

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
                EvidencePortfolio(
                    status="planned",
                    selections=[
                        PortfolioSelection(
                            owner_id="exp1",
                            owner_kind="experience",
                            selected_fact_ids=["b1", "missing"],
                            rank=1,
                            bullet_budget=2,
                            rationale="untrusted note",
                        )
                    ],
                    selected_skill_fact_ids=["missing"],
                    highlight_terms=["missing"],
                )
            )

        async def arun(self, prompt):
            return self.run(prompt)

    config = ReviewConfig(
        max_rounds=1,
        score_threshold=80,
        evidence_portfolio_enabled=True,
        reviewers=[ReviewerSpec(name="ats-keyword", weight=1)],
    )
    tailor_agent = _CapturingTailor()
    planner = _Planner()

    run_tailor_review(
        "Backend",
        JobCriteria(),
        ProfileFacts(
            contact=Contact(name="Ada"),
            experience=[
                Experience(
                    id="exp1",
                    company="Acme",
                    title="Engineer",
                    bullets=[Bullet(id="b1", text="Built an API")],
                )
            ],
        ),
        config,
        tailor_agent,
        {"ats-keyword": _Good("ats-keyword")},
        _ContentAgent(),
        evidence_portfolio_agent=planner,
    )

    assert planner.calls == 1
    assert "EVIDENCE PORTFOLIO" in tailor_agent.prompts[0]
    assert '"status":"planned"' in tailor_agent.prompts[0]
    assert "missing" not in tailor_agent.prompts[0]


def test_enabled_portfolio_without_agent_uses_deterministic_fallback():
    class _CapturingTailor(_ContentAgent):
        def run(self, prompt):
            self.seen = prompt
            return super().run(prompt)

    config = ReviewConfig(max_rounds=1, evidence_portfolio_enabled=True)
    tailor_agent = _CapturingTailor()
    rounds = run_tailor_review(
        "Backend",
        JobCriteria(),
        ProfileFacts(contact=Contact(name="Ada")),
        config,
        tailor_agent,
        {},
        _ContentAgent(),
    )

    assert rounds[0].evidence_portfolio is not None
    assert rounds[0].evidence_portfolio.status == "deterministic_fallback"
    assert '"status":"deterministic_fallback"' in tailor_agent.seen


def test_early_stop_halts_after_clean_score_regression():
    class _Scores:
        def __init__(self):
            self.scores = iter([80, 70, 60])

        def run(self, prompt):
            score = next(self.scores)
            return _Result(
                ReviewCritique(reviewer="ats-keyword", score=score, passed=False)
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


def _round(num: int, *, gate_passed: bool, score: int | None) -> TailorRound:
    return TailorRound(
        round_num=num,
        content=ResumeContent(contact=Contact(name="Ada")),
        verdict=PanelVerdict(
            passed=False, gate_passed=gate_passed, aggregate_score=score
        ),
    )


def test_regression_guard_ignores_unscored_rounds():
    # A clean-but-unscored round carries no quality bar to regress from, so it
    # must neither raise nor count as a baseline.
    assert (
        _has_regressed(
            [
                _round(1, gate_passed=True, score=None),
                _round(2, gate_passed=True, score=50),
            ]
        )
        is False
    )


def test_regression_guard_still_catches_a_real_score_drop():
    assert (
        _has_regressed(
            [
                _round(1, gate_passed=True, score=80),
                _round(2, gate_passed=True, score=60),
            ]
        )
        is True
    )


def test_regression_guard_catches_a_gate_regression():
    assert (
        _has_regressed(
            [
                _round(1, gate_passed=True, score=80),
                _round(2, gate_passed=False, score=90),
            ]
        )
        is True
    )


def test_revision_builds_on_the_best_round_not_the_last():
    # A regressed round used to become the base for the next one, so a bad
    # revision compounded instead of being discarded.
    class _Scores:
        def __init__(self):
            self.scores = iter([80, 60, 90])

        def run(self, prompt):
            return _Result(
                ReviewCritique(
                    reviewer="ats-keyword", score=next(self.scores), passed=False
                )
            )

        async def arun(self, prompt):
            return self.run(prompt)

    class _Reviser:
        """Emits a uniquely named resume each round and records what it was given."""

        def __init__(self):
            self.calls = 0
            self.received = []

        def run(self, prompt):
            self.received.append(prompt)
            self.calls += 1
            return _Result(
                ResumeContent(contact=Contact(name=f"revision-{self.calls}"))
            )

        async def arun(self, prompt):
            return self.run(prompt)

    class _Draft:
        def run(self, prompt):
            return _Result(ResumeContent(contact=Contact(name="draft")))

        async def arun(self, prompt):
            return self.run(prompt)

    reviser = _Reviser()
    rounds = run_tailor_review(
        "jd",
        JobCriteria(),
        ProfileFacts(contact=Contact(name="Ada")),
        ReviewConfig(
            max_rounds=3,
            score_threshold=95,
            early_stop_on_regression=False,
            reviewers=[ReviewerSpec(name="ats-keyword", weight=1)],
        ),
        _Draft(),
        {"ats-keyword": _Scores()},
        reviser,
    )

    assert [r.verdict.aggregate_score for r in rounds] == [80, 60, 90]
    # Round 2 (score 60) regressed from round 1 (score 80), so the third round's
    # revision is composed from round 1's content. Round 2 is present only as
    # diagnostic context for its latest review feedback.
    base_section, latest_section = reviser.received[1].split(
        "LATEST REVIEWED ATTEMPT", maxsplit=1
    )
    assert '"name":"draft"' in base_section
    assert "revision-1" not in base_section
    assert '"name":"revision-1"' in latest_section


class _ClosedLoopFactCheck:
    def __init__(self):
        self.calls = 0

    def run(self, prompt):
        self.calls += 1
        if self.calls == 2:
            return _Result(
                ReviewCritique(
                    reviewer="fact-check",
                    score=0,
                    passed=False,
                    summary="Round two introduced an unsupported metric",
                    issues=[
                        ReviewIssue(
                            severity=Severity.blocking,
                            message="Remove the unsupported 400-hour claim",
                        )
                    ],
                )
            )
        return _Result(
            ReviewCritique(
                reviewer="fact-check",
                score=100,
                passed=True,
                summary=f"fact-check-clean-round-{self.calls}",
            )
        )

    async def arun(self, prompt):
        return self.run(prompt)


class _ClosedLoopScores:
    def __init__(self):
        self.scores = iter([80, 90, 96])

    def run(self, prompt):
        score = next(self.scores)
        return _Result(
            ReviewCritique(
                reviewer="ats-keyword",
                score=score,
                passed=score >= 95,
                summary=f"ats-score-{score}",
            )
        )

    async def arun(self, prompt):
        return self.run(prompt)


class _ClosedLoopDraft:
    def __init__(self, name):
        self.name = name

    def run(self, prompt):
        return _Result(ResumeContent(contact=Contact(name=self.name)))

    async def arun(self, prompt):
        return self.run(prompt)


class _ClosedLoopReviser:
    def __init__(self, prefix):
        self.prefix = prefix
        self.calls = 0
        self.received = []

    def run(self, prompt):
        self.received.append(prompt)
        self.calls += 1
        return _Result(
            ResumeContent(contact=Contact(name=f"{self.prefix}-{self.calls}"))
        )

    async def arun(self, prompt):
        return self.run(prompt)


def _closed_loop_config():
    return ReviewConfig(
        max_rounds=3,
        score_threshold=95,
        early_stop_on_regression=False,
        reviewers=[
            ReviewerSpec(name="fact-check", gate=True, weight=0),
            ReviewerSpec(name="ats-keyword", weight=1),
        ],
    )


def test_regressed_round_uses_best_base_with_latest_fact_check_feedback():
    reviser = _ClosedLoopReviser("revision")
    rounds = run_tailor_review(
        "jd",
        JobCriteria(),
        ProfileFacts(contact=Contact(name="Ada")),
        _closed_loop_config(),
        _ClosedLoopDraft("safe-draft"),
        {
            "fact-check": _ClosedLoopFactCheck(),
            "ats-keyword": _ClosedLoopScores(),
        },
        reviser,
    )

    assert [round_.verdict.aggregate_score for round_ in rounds] == [80, 90, 96]
    third_round_prompt = reviser.received[1]
    assert "REVISION BASE RESUME (round 1)" in third_round_prompt
    assert '"name":"safe-draft"' in third_round_prompt
    assert (
        "LATEST REVIEWED ATTEMPT (round 2; diagnostic reference only)"
        in third_round_prompt
    )
    assert '"name":"revision-1"' in third_round_prompt
    assert "Failed gates: fact-check" in third_round_prompt
    assert "Round two introduced an unsupported metric" in third_round_prompt
    assert "Remove the unsupported 400-hour claim" in third_round_prompt
    assert "ats-score-90" in third_round_prompt
    assert "fact-check-clean-round-1" not in third_round_prompt


def test_async_regressed_round_uses_best_base_with_latest_fact_check_feedback():
    import asyncio

    from resume_agent.tailor.workflow import arun_tailor_review

    reviser = _ClosedLoopReviser("async-revision")

    async def go():
        return await arun_tailor_review(
            "jd",
            JobCriteria(),
            ProfileFacts(contact=Contact(name="Ada")),
            _closed_loop_config(),
            _ClosedLoopDraft("async-safe-draft"),
            {
                "fact-check": _ClosedLoopFactCheck(),
                "ats-keyword": _ClosedLoopScores(),
            },
            reviser,
            sem=asyncio.Semaphore(4),
        )

    rounds = asyncio.run(go())

    assert [round_.verdict.aggregate_score for round_ in rounds] == [80, 90, 96]
    third_round_prompt = reviser.received[1]
    assert "REVISION BASE RESUME (round 1)" in third_round_prompt
    assert '"name":"async-safe-draft"' in third_round_prompt
    assert (
        "LATEST REVIEWED ATTEMPT (round 2; diagnostic reference only)"
        in third_round_prompt
    )
    assert '"name":"async-revision-1"' in third_round_prompt
    assert "Failed gates: fact-check" in third_round_prompt
    assert "Round two introduced an unsupported metric" in third_round_prompt
    assert "Remove the unsupported 400-hour claim" in third_round_prompt


def test_revision_base_is_unchanged_when_rounds_improve():
    # Regression guard: monotonic improvement must behave exactly as before.
    class _Scores:
        def __init__(self):
            self.scores = iter([50, 70, 90])

        def run(self, prompt):
            return _Result(
                ReviewCritique(
                    reviewer="ats-keyword", score=next(self.scores), passed=False
                )
            )

        async def arun(self, prompt):
            return self.run(prompt)

    class _Reviser:
        def __init__(self):
            self.calls = 0
            self.received = []

        def run(self, prompt):
            self.received.append(prompt)
            self.calls += 1
            return _Result(
                ResumeContent(contact=Contact(name=f"revision-{self.calls}"))
            )

        async def arun(self, prompt):
            return self.run(prompt)

    class _Draft:
        def run(self, prompt):
            return _Result(ResumeContent(contact=Contact(name="draft")))

        async def arun(self, prompt):
            return self.run(prompt)

    reviser = _Reviser()
    run_tailor_review(
        "jd",
        JobCriteria(),
        ProfileFacts(contact=Contact(name="Ada")),
        ReviewConfig(
            max_rounds=3,
            score_threshold=95,
            early_stop_on_regression=False,
            reviewers=[ReviewerSpec(name="ats-keyword", weight=1)],
        ),
        _Draft(),
        {"ats-keyword": _Scores()},
        reviser,
    )

    assert "revision-1" in reviser.received[1]


def _slip_config(budget: int) -> ReviewConfig:
    return ReviewConfig(
        max_rounds=2,
        # Unreachable on purpose: these tests measure how many rounds the budget
        # buys, so the loop must run to exhaustion rather than stopping on success.
        score_threshold=99,
        provenance_retry_budget=budget,
        reviewers=[
            ReviewerSpec(name="fact-check", gate=True, weight=0),
            ReviewerSpec(name="ats-keyword", weight=1),
        ],
    )


class _BrokenThenFixed:
    """Cites a ghost id on the first draft, a real one afterwards."""

    def __init__(self):
        self.calls = 0

    def run(self, prompt):
        self.calls += 1
        return _Result(
            ResumeContent(
                contact=Contact(name="Ada"),
                experience=[
                    TailoredExperience(
                        company="AE",
                        title="Eng",
                        provenance="e1",
                        bullets=[
                            TailoredBullet(
                                text="X",
                                provenance="ghost" if self.calls == 1 else "b1",
                            )
                        ],
                    )
                ],
            )
        )

    async def arun(self, prompt):
        return self.run(prompt)


def _slip_facts() -> ProfileFacts:
    return ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[
            Experience(
                id="e1", company="AE", title="Eng", bullets=[Bullet(id="b1", text="X")]
            )
        ],
    )


def test_citation_slip_does_not_consume_a_quality_round():
    # max_rounds=2, but round 1 failed only on a bad provenance id. Burning a
    # quality pass on a typo left exactly one real review and no round to act on it.
    drafter = _BrokenThenFixed()
    rounds = run_tailor_review(
        "jd",
        JobCriteria(),
        _slip_facts(),
        _slip_config(budget=1),
        drafter,
        {"fact-check": _Good("fact-check"), "ats-keyword": _Good("ats-keyword")},
        drafter,
    )
    assert len(rounds) == 3
    assert rounds[0].verdict.gate_passed is False
    assert rounds[-1].verdict.gate_passed is True


def test_citation_slip_budget_is_bounded():
    class _AlwaysBroken:
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

    rounds = run_tailor_review(
        "jd",
        JobCriteria(),
        _slip_facts(),
        _slip_config(budget=1),
        _AlwaysBroken(),
        {"fact-check": _Good("fact-check"), "ats-keyword": _Good("ats-keyword")},
        _AlwaysBroken(),
    )
    assert len(rounds) == 3  # 2 configured + 1 free, then it stops


def test_zero_budget_reproduces_the_old_round_counting():
    drafter = _BrokenThenFixed()
    rounds = run_tailor_review(
        "jd",
        JobCriteria(),
        _slip_facts(),
        _slip_config(budget=0),
        drafter,
        {"fact-check": _Good("fact-check"), "ats-keyword": _Good("ats-keyword")},
        drafter,
    )
    assert len(rounds) == 2


def test_a_round_failing_the_fact_check_gate_too_is_not_a_free_retry():
    # Only a citation slip is free. A resume the panel also rejects needs a real
    # revision round, and a free retry would just spend tokens.
    class _FailGate:
        def run(self, prompt):
            return _Result(ReviewCritique(reviewer="fact-check", score=0, passed=False))

        async def arun(self, prompt):
            return self.run(prompt)

    rounds = run_tailor_review(
        "jd",
        JobCriteria(),
        _slip_facts(),
        _slip_config(budget=1),
        _BrokenThenFixed(),
        {"fact-check": _FailGate(), "ats-keyword": _Good("ats-keyword")},
        _BrokenThenFixed(),
    )
    assert len(rounds) == 2
