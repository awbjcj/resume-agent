import pytest
from pydantic import ValidationError

from resume_agent.llm_runner import AgentRunner

from resume_agent.discovery.fit import (
    FitLocation,
    FitScore,
    build_fit_agent,
    compose_fit_input,
    score_fit,
)
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
    assert isinstance(build_fit_agent(model_id="claude-haiku-4-5-20251001"), AgentRunner)


def test_fitscore_defaults_keep_existing_construction():
    fit = FitScore(score=90, rationale="great")
    assert fit.sic_major is None
    assert fit.location is None


def test_score_fit_returns_new_fields():
    payload = FitScore(
        score=80, rationale="ok", sic_major="73",
        location=FitLocation(city="Austin", region="TX", country="USA"),
    )
    fit = score_fit("x", _FakeAgent(payload))
    assert fit.sic_major == "73"
    assert fit.location is not None
    assert fit.location.city == "Austin"


def test_compose_fit_input_includes_location():
    facts = ProfileFacts(contact=Contact(name="Ada"))
    text = compose_fit_input("the jd", facts, location="Austin, TX")
    assert "Austin, TX" in text
    assert "the jd" in text
