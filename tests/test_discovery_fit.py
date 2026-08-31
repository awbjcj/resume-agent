import pytest
from pydantic import ValidationError

from resume_tailor_harness.llm_runner import AgentRunner

from resume_tailor_harness.discovery.fit import (
    FitLocation,
    FitScore,
    build_fit_agent,
    compose_fit_input,
    score_fit,
)
from resume_tailor_harness.models.profile import Contact, ProfileFacts
from resume_tailor_harness.profile.matrix import MatrixRow, SkillMatch, SkillMatchContext


class _FakeResult:
    def __init__(self, content):
        self.content = content


class _FakeAgent:
    def __init__(self, content):
        self._content = content

    def run(self, prompt):
        return _FakeResult(self._content)

    async def arun(self, prompt):
        return self.run(prompt)


def test_compose_includes_profile_and_jd():
    facts = ProfileFacts(contact=Contact(name="Ada Lovelace"))
    text = compose_fit_input("Backend role", facts)
    assert "Ada Lovelace" in text
    assert "Backend role" in text
    assert "SKILL MATCH CONTEXT" not in text


def test_compose_fit_input_appends_deterministic_skill_context():
    context = SkillMatchContext(
        matches=[
            SkillMatch(
                requirement="FastAPI",
                source="must",
                coverage="adjacent",
                row=MatrixRow(key="flask", display="Flask", strength=2.0),
            )
        ]
    )
    text = compose_fit_input(
        "JD",
        ProfileFacts(contact=Contact(name="Ada")),
        "Remote",
        skill_context=context,
    )
    assert "SKILL MATCH CONTEXT (JSON):" in text
    assert '"coverage":"adjacent"' in text


def test_score_fit_returns_fitscore():
    fit = FitScore(score=82, rationale="strong overlap")
    out = score_fit("input", _FakeAgent(fit))
    assert out.score == 82


def test_ascore_fit_uses_arun():
    import asyncio

    from resume_tailor_harness.discovery.fit import ascore_fit

    class _AsyncAgent:
        def run(self, prompt):
            raise NotImplementedError

        async def arun(self, prompt):
            return _FakeResult(FitScore(score=88, rationale="ok"))

    out = asyncio.run(ascore_fit("input", _AsyncAgent(), sem=asyncio.Semaphore(2)))
    assert isinstance(out, FitScore) and out.score == 88


def test_fit_score_rejects_out_of_range_score():
    with pytest.raises(ValidationError):
        FitScore(score=101, rationale="too high")


def test_score_fit_rejects_wrong_type():
    with pytest.raises(TypeError):
        score_fit("x", _FakeAgent("nope"))


def test_build_fit_agent_is_agent(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert isinstance(
        build_fit_agent(model_id="claude-haiku-4-5-20251001"), AgentRunner
    )


def test_fitscore_defaults_keep_existing_construction():
    fit = FitScore(score=90, rationale="great")
    assert fit.location is None


def test_fit_location_requires_country_but_allows_city_and_region_to_be_omitted():
    location = FitLocation(country="Singapore")
    assert location.city is None
    assert location.region is None

    with pytest.raises(ValidationError):
        FitLocation.model_validate({"city": "Singapore"})


def test_score_fit_returns_location():
    payload = FitScore(
        score=80,
        rationale="ok",
        location=FitLocation(city="Austin", region="TX", country="USA"),
    )
    fit = score_fit("x", _FakeAgent(payload))
    assert fit.location is not None
    assert fit.location.city == "Austin"


def test_compose_fit_input_includes_location():
    facts = ProfileFacts(contact=Contact(name="Ada"))
    text = compose_fit_input("the jd", facts, location="Austin, TX")
    assert "Austin, TX" in text
    assert "the jd" in text
