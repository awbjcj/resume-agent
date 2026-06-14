from resume_agent.llm_runner import AgentRunner

from resume_agent.models.resume import ResumeContent
from resume_agent.models.review import ReviewCritique
from resume_agent.tailor.agents import (
    _TAILOR_INSTRUCTIONS,
    build_reviewer_agent,
    build_reviser_agent,
    build_tailor_agent,
    model_for_tier,
)


def test_model_for_tier_maps_known_tiers():
    assert model_for_tier("cheap")
    assert model_for_tier("mid")
    assert model_for_tier("premium")
    # unknown tier falls back to the mid model
    assert model_for_tier("bogus") == model_for_tier("mid")


def test_build_tailor_and_reviser_agents(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert isinstance(build_tailor_agent(model_id="claude-haiku-4-5-20251001"), AgentRunner)
    assert isinstance(build_reviser_agent(model_id="claude-haiku-4-5-20251001"), AgentRunner)


def test_build_reviewer_agent(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    agent = build_reviewer_agent("fact-check", model_id="claude-haiku-4-5-20251001")
    assert isinstance(agent, AgentRunner)


def test_tailor_agent_includes_style_and_keeps_factlock(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    agent = build_tailor_agent(
        model_id="claude-haiku-4-5-20251001",
        style_guide="Use British spelling.",
    )
    assert isinstance(agent, AgentRunner)
    rendered = str(agent._agent.instructions)

    assert _TAILOR_INSTRUCTIONS[1] in rendered
    assert "HOUSE STYLE" in rendered
    assert "Use British spelling." in rendered


def test_reviewer_agent_includes_style(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    agent = build_reviewer_agent(
        "recruiter",
        model_id="claude-haiku-4-5-20251001",
        style_guide="Prefer STAR phrasing.",
    )

    assert isinstance(agent, AgentRunner)
    assert "Prefer STAR phrasing." in str(agent._agent.instructions)


def test_reviser_agent_without_style_is_unchanged(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")

    agent = build_reviser_agent(model_id="claude-haiku-4-5-20251001")

    assert isinstance(agent, AgentRunner)
    assert "HOUSE STYLE" not in str(agent._agent.instructions)
