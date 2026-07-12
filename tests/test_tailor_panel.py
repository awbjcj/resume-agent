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
        self.received: str = ""

    def run(self, prompt: str):
        self.received = prompt
        return _Result(self._content)

    async def arun(self, prompt: str):
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


def test_split_merged_critiques_returns_config_order():
    from resume_agent.models.review import MergedPanelReview
    from resume_agent.tailor.panel import split_merged_critiques

    review = MergedPanelReview(
        critiques=[
            ReviewCritique(reviewer="recruiter", score=88, passed=True),
            ReviewCritique(reviewer="ats-keyword", score=82, passed=True),
        ]
    )

    result = split_merged_critiques(review, ["ats-keyword", "recruiter"])

    assert [critique.reviewer for critique in result] == ["ats-keyword", "recruiter"]


@pytest.mark.parametrize(
    "names",
    [
        ["ats-keyword"],
        ["ats-keyword", "recruiter", "extra"],
        ["ats-keyword", "ats-keyword", "recruiter"],
    ],
)
def test_split_merged_critiques_rejects_wrong_coverage(names):
    from resume_agent.models.review import MergedPanelReview
    from resume_agent.tailor.panel import split_merged_critiques

    review = MergedPanelReview(
        critiques=[ReviewCritique(reviewer=name, score=80, passed=True) for name in names]
    )

    with pytest.raises(ValueError):
        split_merged_critiques(review, ["ats-keyword", "recruiter"])


def test_merged_advisory_instructions_include_each_rubric():
    from resume_agent.tailor.agents import _merged_advisory_instructions

    text = " ".join(_merged_advisory_instructions(["ats-keyword", "concision"]))
    assert "'ats-keyword'" in text
    assert "'concision'" in text
    assert "keyword" in text.lower()
    assert "concision" in text.lower()


def test_merged_advisory_instructions_apply_score_bands_per_reviewer():
    from resume_agent.tailor.agents import (
        _SCORE_BAND_INSTRUCTION,
        _merged_advisory_instructions,
    )

    instructions = _merged_advisory_instructions(
        ["ats-keyword", "concision"],
        score_bands={"ats-keyword": True, "concision": False},
    )
    by_rubric = {
        line.split("'")[1]: line
        for line in instructions
        if line.startswith("Rubric for")
    }
    assert _SCORE_BAND_INSTRUCTION in by_rubric["ats-keyword"]
    assert _SCORE_BAND_INSTRUCTION not in by_rubric["concision"]


def _merged_config() -> ReviewConfig:
    return ReviewConfig(
        merged_advisory=True,
        reviewers=[
            ReviewerSpec(name="fact-check", gate=True, weight=0),
            ReviewerSpec(name="ats-keyword"),
            ReviewerSpec(name="recruiter"),
        ],
    )


def test_run_panel_merged_makes_one_lean_advisory_call():
    from resume_agent.models.review import MergedPanelReview
    from resume_agent.tailor.panel import MERGED_ADVISORY

    merged = _Agent(
        MergedPanelReview(
            critiques=[
                ReviewCritique(reviewer="recruiter", score=88, passed=True),
                ReviewCritique(reviewer="ats-keyword", score=82, passed=True),
            ]
        )
    )
    reviewers = {
        "fact-check": _Agent(
            ReviewCritique(reviewer="fact-check", score=100, passed=True)
        ),
        MERGED_ADVISORY: merged,
    }

    critiques = run_panel(_content(), _facts(), "Backend role", _merged_config(), reviewers)

    assert [critique.reviewer for critique in critiques] == [
        "fact-check",
        "ats-keyword",
        "recruiter",
    ]
    assert "SUPPORTING FACTS" in reviewers["fact-check"].received
    assert "RESUME STATS" in merged.received
    assert "SecretRust" not in merged.received


def test_arun_panel_merged_matches_sync_order():
    import asyncio

    from resume_agent.models.review import MergedPanelReview
    from resume_agent.tailor.panel import MERGED_ADVISORY, arun_panel

    reviewers = {
        "fact-check": _Agent(
            ReviewCritique(reviewer="fact-check", score=100, passed=True)
        ),
        MERGED_ADVISORY: _Agent(
            MergedPanelReview(
                critiques=[
                    ReviewCritique(reviewer="ats-keyword", score=82, passed=True),
                    ReviewCritique(reviewer="recruiter", score=88, passed=True),
                ]
            )
        ),
    }

    critiques = asyncio.run(
        arun_panel(
            _content(),
            _facts(),
            "jd",
            _merged_config(),
            reviewers,
            sem=asyncio.Semaphore(8),
        )
    )

    assert [critique.reviewer for critique in critiques] == [
        "fact-check",
        "ats-keyword",
        "recruiter",
    ]
