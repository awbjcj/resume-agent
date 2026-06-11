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
    assert "SecretRust" not in agents["ats-keyword"].received
    assert "SUPPORTING FACTS" in agents["fact-check"].received
