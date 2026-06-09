import pytest

from resume_agent.models.profile import Contact, ProfileFacts
from resume_agent.models.resume import ResumeContent
from resume_agent.models.review import ReviewCritique
from resume_agent.tailor.panel import compose_review_input, review_one, run_panel
from resume_agent.tailor.review_config import ReviewConfig, ReviewerSpec


class _Result:
    def __init__(self, content):
        self.content = content


class _Agent:
    def __init__(self, content):
        self._content = content

    def run(self, prompt):
        return _Result(self._content)


def test_compose_review_input_has_profile_resume_jd():
    rc = ResumeContent(contact=Contact(name="Ada Lovelace"))
    facts = ProfileFacts(contact=Contact(name="Ada Lovelace"))
    text = compose_review_input(rc, facts, "Backend role")
    assert "Ada Lovelace" in text
    assert "Backend role" in text


def test_review_one_returns_critique():
    crit = ReviewCritique(reviewer="fact-check", score=100, passed=True)
    assert review_one("input", _Agent(crit)) is crit


def test_review_one_rejects_wrong_type():
    with pytest.raises(TypeError):
        review_one("x", _Agent("nope"))


def test_run_panel_runs_every_configured_reviewer():
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
    critiques = run_panel("input", config, agents)
    assert [c.reviewer for c in critiques] == ["fact-check", "ats-keyword"]
