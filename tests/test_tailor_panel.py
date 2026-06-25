import pytest

from resume_agent.models.profile import (
    Bullet,
    Contact,
    Experience,
    ProfileFacts,
    Skill,
)
from resume_agent.models.resume import (
    ResumeContent,
    TailoredBullet,
    TailoredExperience,
    TailoredSkill,
)
from resume_agent.models.review import ReviewCritique
from resume_agent.tailor.panel import (
    compose_evidence_review_input,
    compose_lean_review_input,
    review_one,
    run_panel,
)
from resume_agent.tailor.review_config import ReviewConfig, ReviewerSpec


class _Result:
    def __init__(self, content):
        self.content = content


class _Agent:
    def __init__(self, content):
        self._content = content
        self.received = None

    def run(self, prompt):
        self.received = prompt
        return _Result(self._content)

    async def arun(self, prompt):
        return self.run(prompt)


def _facts() -> ProfileFacts:
    return ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[
            Experience(
                id="e1",
                company="AE",
                title="Eng",
                bullets=[Bullet(id="b1", text="Built X")],
            )
        ],
        skills={"languages": [Skill(id="s1", name="Python"), Skill(id="s2", name="SecretRust")]},
    )


def _content() -> ResumeContent:
    return ResumeContent(
        contact=Contact(name="Ada"),
        experience=[
            TailoredExperience(
                company="AE",
                title="Eng",
                provenance="e1",
                bullets=[TailoredBullet(text="Built X", provenance="b1")],
            )
        ],
        skills={"languages": [TailoredSkill(name="Python", provenance="s1")]},
    )


def test_lean_input_has_no_raw_profile():
    text = compose_lean_review_input(_content(), "Backend role", "experiences=1")
    assert "Backend role" in text
    assert "experiences=1" in text
    assert "SecretRust" not in text


def test_evidence_input_carries_only_referenced_facts():
    from resume_agent.tailor.provenance import resolve_evidence

    evidence = resolve_evidence(_content(), _facts())
    text = compose_evidence_review_input(_content(), "Backend role", evidence)
    assert "b1" in text
    assert "SecretRust" not in text


def test_review_one_rejects_wrong_type():
    with pytest.raises(TypeError):
        review_one("x", _Agent("nope"))


def test_run_panel_routes_gate_to_evidence_and_others_to_lean():
    config = ReviewConfig(
        reviewers=[
            ReviewerSpec(name="fact-check", gate=True, weight=0),
            ReviewerSpec(name="ats-keyword", weight=1),
        ]
    )
    agents = {
        "fact-check": _Agent(ReviewCritique(reviewer="fact-check", score=100, passed=True)),
        "ats-keyword": _Agent(ReviewCritique(reviewer="ats-keyword", score=80, passed=True)),
    }
    critiques = run_panel(_content(), _facts(), "Backend role", config, agents)

    assert [c.reviewer for c in critiques] == ["fact-check", "ats-keyword"]
    assert agents["ats-keyword"].received is not None
    assert agents["fact-check"].received is not None
    assert "SecretRust" not in agents["ats-keyword"].received
    assert "SUPPORTING FACTS" in agents["fact-check"].received


def test_arun_panel_runs_reviewers_concurrently_in_order():
    import asyncio
    import time

    from resume_agent.tailor.panel import arun_panel

    config = ReviewConfig(
        reviewers=[ReviewerSpec(name="a"), ReviewerSpec(name="b"), ReviewerSpec(name="c")]
    )

    class _Slow:
        def __init__(self, name):
            self.name = name

        def run(self, prompt):
            raise NotImplementedError

        async def arun(self, prompt):
            await asyncio.sleep(0.05)
            return _Result(ReviewCritique(reviewer=self.name, score=80, passed=True))

    agents = {n: _Slow(n) for n in ("a", "b", "c")}

    async def go():
        return await arun_panel(
            _content(), _facts(), "jd", config, agents, sem=asyncio.Semaphore(8)
        )

    t0 = time.perf_counter()
    critiques = asyncio.run(go())
    elapsed = time.perf_counter() - t0

    assert [c.reviewer for c in critiques] == ["a", "b", "c"]
    assert elapsed < 0.12


def test_arun_panel_settles_reviewers_before_raising():
    import asyncio

    from resume_agent.tailor.panel import arun_panel

    config = ReviewConfig(reviewers=[ReviewerSpec(name="boom"), ReviewerSpec(name="slow")])
    events: list[str] = []

    class _AsyncAgent:
        def __init__(self, name, *, fail=False):
            self.name = name
            self.fail = fail

        def run(self, prompt):
            raise NotImplementedError

        async def arun(self, prompt):
            events.append(f"{self.name}:start")
            await asyncio.sleep(0.01 if self.fail else 0.05)
            if self.fail:
                events.append(f"{self.name}:raise")
                raise RuntimeError("reviewer down")
            events.append(f"{self.name}:done")
            return _Result(ReviewCritique(reviewer=self.name, score=80, passed=True))

    agents = {"boom": _AsyncAgent("boom", fail=True), "slow": _AsyncAgent("slow")}

    async def go():
        return await arun_panel(
            _content(), _facts(), "jd", config, agents, sem=asyncio.Semaphore(8)
        )

    with pytest.raises(RuntimeError):
        asyncio.run(go())
    assert "slow:done" in events
