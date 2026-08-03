"""Structural boundaries for Career Lab's router, persona, and formatter."""

from types import SimpleNamespace

from resume_agent.config import Settings
from resume_agent.career_lab import agents
from resume_agent.career_skills.models import AgentFamily
from resume_agent.career_skills.registry import CareerSkillRegistry
from resume_agent.llm_runner import AgentRunner


def test_builders_keep_router_and_formatter_tool_free(monkeypatch):
    captured = []

    class FakeAgent:
        def __init__(self, **kwargs):
            captured.append(kwargs)

    monkeypatch.setattr(agents, "Agent", FakeAgent)
    monkeypatch.setattr(agents, "build_model", lambda *args, **kwargs: "model")
    monkeypatch.setattr(
        agents,
        "provider_capabilities",
        lambda *_args, **_kwargs: SimpleNamespace(supports_prompt_cache=False),
    )
    monkeypatch.setattr(
        agents,
        "get_settings",
        lambda: Settings(_env_file=None, cheap_model="cheap", mid_model="mid"),  # type: ignore[call-arg]
    )

    router = agents.build_router_agent()
    formatter = agents.build_formatter_agent()

    assert isinstance(router, AgentRunner)
    assert isinstance(formatter, AgentRunner)
    assert router.run_meta is not None
    assert formatter.run_meta is not None
    assert router.run_meta.agent_family is AgentFamily.CAREER_LAB
    assert formatter.run_meta.skill_ref is None
    assert captured[0].get("tools") is None
    assert captured[0].get("skills") is None
    assert captured[1].get("tools") is None
    assert captured[1].get("skills") is None
    assert captured[0]["output_schema"].__name__ == "CareerLabRoute"
    assert captured[1]["output_schema"].__name__ == "CareerLabArtifactMeta"


def test_persona_builder_attaches_one_verified_local_skill(monkeypatch):
    captured = []

    class FakeAgent:
        def __init__(self, **kwargs):
            captured.append(kwargs)

    monkeypatch.setattr(agents, "Agent", FakeAgent)
    monkeypatch.setattr(agents, "build_model", lambda *args, **kwargs: "model")
    monkeypatch.setattr(
        agents,
        "provider_capabilities",
        lambda *_args, **_kwargs: SimpleNamespace(supports_prompt_cache=False),
    )
    monkeypatch.setattr(
        agents,
        "get_settings",
        lambda: Settings(_env_file=None, mid_model="mid"),  # type: ignore[call-arg]
    )
    skill = CareerSkillRegistry.from_paths("skills", "skills-lock.json").require(
        "salary-negotiation-prep", family=AgentFamily.CAREER_LAB, use="career_lab"
    )

    persona = agents.build_persona_agent(skill)

    assert isinstance(persona, AgentRunner)
    assert persona.run_meta is not None
    assert persona.run_meta.skill_ref == skill.ref
    assert captured[0]["skills"].loaders
    assert len(captured[0]["skills"].loaders) == 1
    assert captured[0].get("tools") is None
