import pytest
from pydantic import ValidationError

from agno.agent import Agent

from resume_agent.discovery.fit import FitScore, build_fit_agent, compose_fit_input, score_fit
from resume_agent.models.profile import Contact, ProfileFacts


class _FakeResult:
    def __init__(self, content):
        self.content = content


class _FakeAgent:
    def __init__(self, content):
        self._content = content

    def run(self, prompt):
        return _FakeResult(self._content)


def test_compose_includes_profile_and_jd():
    facts = ProfileFacts(contact=Contact(name="Ada Lovelace"))
    text = compose_fit_input("Backend role", facts)
    assert "Ada Lovelace" in text
    assert "Backend role" in text


def test_score_fit_returns_fitscore():
    fit = FitScore(score=82, rationale="strong overlap")
    out = score_fit("input", _FakeAgent(fit))
    assert out.score == 82


def test_fit_score_rejects_out_of_range_score():
    with pytest.raises(ValidationError):
        FitScore(score=101, rationale="too high")


def test_score_fit_rejects_wrong_type():
    with pytest.raises(TypeError):
        score_fit("x", _FakeAgent("nope"))


def test_build_fit_agent_is_agent(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert isinstance(build_fit_agent(model_id="claude-haiku-4-5-20251001"), Agent)
