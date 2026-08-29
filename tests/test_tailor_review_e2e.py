"""End-to-end guards for the tailor review loop, with every agent faked.

These pin the behaviours the 2026-07-27 repair depends on. The last test is the
important one: if a fabricated metric ever stops failing the round, fact-lock has
been weakened and the rest of this file is worthless.
"""

from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import Bullet, Contact, Experience, ProfileFacts, Skill
from resume_agent.models.resume import (
    ResumeContent,
    TailoredBullet,
    TailoredExperience,
    TailoredSkill,
)
from resume_agent.models.review import ReviewCritique, ReviewIssue, Severity
from resume_agent.tailor.review_config import ReviewConfig, ReviewerSpec
from resume_agent.tailor.workflow import run_tailor_review


class _Result:
    def __init__(self, content):
        self.content = content


class _Recorder:
    """A reviewer that always passes and remembers every prompt it was given."""

    def __init__(self, name):
        self.name = name
        self.received = []

    def run(self, prompt):
        self.received.append(prompt)
        return _Result(ReviewCritique(reviewer=self.name, score=90, passed=True))

    async def arun(self, prompt):
        return self.run(prompt)


def _facts() -> ProfileFacts:
    return ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[
            Experience(
                id="e1",
                company="Acme",
                title="Engineer",
                bullets=[Bullet(id="b1", text="Built a reporting pipeline")],
            )
        ],
        skills={
            "hard": [Skill(id="s1", name="Python")],
            "soft": [
                Skill(
                    id="forbidden",
                    name="Stakeholder Communication",
                    inferred=True,
                    category="soft",
                    evidence_fact_ids=["b1"],
                )
            ],
        },
    )


def _clean_resume() -> ResumeContent:
    return ResumeContent(
        contact=Contact(name="Ada"),
        summary="Engineer who built a reporting pipeline.",
        summary_provenance=["b1"],
        experience=[
            TailoredExperience(
                company="Acme",
                title="Engineer",
                provenance="e1",
                bullets=[
                    TailoredBullet(text="Built a reporting pipeline", provenance="b1")
                ],
            )
        ],
        skills={"hard": [TailoredSkill(name="Python", provenance="s1")]},
    )


def _config(**overrides) -> ReviewConfig:
    base = {
        "max_rounds": 2,
        "score_threshold": 85,
        "reviewers": [
            ReviewerSpec(name="fact-check", gate=True, weight=0),
            ReviewerSpec(name="ats-keyword", weight=1),
        ],
    }
    base.update(overrides)
    return ReviewConfig(**base)


class _FixedWriter:
    def __init__(self, content):
        self.content = content
        self.received = []

    def run(self, prompt):
        self.received.append(prompt)
        return _Result(self.content)

    async def arun(self, prompt):
        return self.run(prompt)


def test_the_writer_is_never_offered_an_unrenderable_fact():
    writer = _FixedWriter(_clean_resume())
    run_tailor_review(
        "Backend role",
        JobCriteria(),
        _facts(),
        _config(),
        writer,
        {
            "fact-check": _Recorder("fact-check"),
            "ats-keyword": _Recorder("ats-keyword"),
        },
        writer,
    )
    assert "forbidden" not in writer.received[0]
    assert "Stakeholder Communication" not in writer.received[0]
    assert "Python" in writer.received[0]


def test_the_reviser_receives_the_job_description():
    class _Weak:
        def run(self, prompt):
            return _Result(
                ReviewCritique(reviewer="ats-keyword", score=10, passed=False)
            )

        async def arun(self, prompt):
            return self.run(prompt)

    reviser = _FixedWriter(_clean_resume())
    run_tailor_review(
        "Backend role: FastAPI and Postgres",
        JobCriteria(),
        _facts(),
        _config(),
        _FixedWriter(_clean_resume()),
        {"fact-check": _Recorder("fact-check"), "ats-keyword": _Weak()},
        reviser,
    )
    assert reviser.received, "the loop never revised"
    assert "FastAPI and Postgres" in reviser.received[0]


def test_a_citation_slip_scores_normally_gets_a_retry_and_still_fails_its_gate():
    class _GhostThenClean:
        def __init__(self):
            self.calls = 0

        def run(self, prompt):
            self.calls += 1
            if self.calls == 1:
                broken = _clean_resume()
                broken.experience[0].bullets[0].provenance = "ghost"
                return _Result(broken)
            return _Result(_clean_resume())

        async def arun(self, prompt):
            return self.run(prompt)

    agent = _GhostThenClean()
    rounds = run_tailor_review(
        "Backend role",
        JobCriteria(),
        _facts(),
        _config(score_threshold=1),
        agent,
        {
            "fact-check": _Recorder("fact-check"),
            "ats-keyword": _Recorder("ats-keyword"),
        },
        agent,
    )

    first = rounds[0].verdict
    # The panel ran, so the score is a real measurement, not a fabricated 0...
    assert first.aggregate_score == 90
    # ...but the gate still blocked the round.
    assert first.gate_passed is False
    assert first.passed is False
    # The reviser had real advisory critiques to work with, not just the
    # citation complaint - that is what the panel skip used to cost.
    assert [c.reviewer for c in first.critiques] == [
        "provenance",
        "skill-naming",
        "numeric-evidence",
        "bullet-depth",
        "fact-check",
        "ats-keyword",
    ]
    # And the loop recovered to a clean passing round.
    assert rounds[-1].verdict.passed is True
    assert rounds[-1].verdict.gate_passed is True


def test_a_fabricated_metric_still_fails_the_round():
    """THE anti-regression test for the whole 2026-07-27 repair.

    Every other change narrows what the writer can produce or fixes what the
    runtime reports. None of them may make the gate easier to pass. If this test
    ever goes green for the wrong reason, fact-lock has been broken.
    """

    class _Fabricator:
        def run(self, prompt):
            resume = _clean_resume()
            resume.experience[0].bullets[
                0
            ].text = "Built a reporting pipeline, saving 400 engineer-hours a quarter"
            return _Result(resume)

        async def arun(self, prompt):
            return self.run(prompt)

    class _CatchesIt:
        def run(self, prompt):
            return _Result(
                ReviewCritique(
                    reviewer="fact-check",
                    score=0,
                    passed=False,
                    issues=[
                        ReviewIssue(
                            severity=Severity.blocking,
                            message="'400 engineer-hours' is not in the source fact",
                        )
                    ],
                )
            )

        async def arun(self, prompt):
            return self.run(prompt)

    rounds = run_tailor_review(
        "Backend role",
        JobCriteria(),
        _facts(),
        _config(score_threshold=1),
        _Fabricator(),
        {"fact-check": _CatchesIt(), "ats-keyword": _Recorder("ats-keyword")},
        _Fabricator(),
    )

    assert all(round_.verdict.gate_passed is False for round_ in rounds)
    assert all(round_.verdict.passed is False for round_ in rounds)
    # Provenance is clean here - the resume cites real ids and simply lies about
    # them - so this must be caught by the fact-check gate, not by provenance.
    assert rounds[-1].verdict.critiques[0].reviewer == "provenance"
    assert rounds[-1].verdict.critiques[0].passed is True
