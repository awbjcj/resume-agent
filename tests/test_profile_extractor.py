import pytest

from resume_agent.llm_runner import AgentRunner

from resume_agent.models.profile import Contact, ProfileFacts
from resume_agent.profile.extractor import build_extractor_agent, extract_profile_facts


class _FakeResult:
    def __init__(self, content):
        self.content = content


class _FakeAgent:
    def __init__(self, content):
        self._content = content
        self.received = None

    def run(self, prompt):
        self.received = prompt
        return _FakeResult(self._content)

    async def arun(self, prompt):
        return self.run(prompt)


def test_extract_returns_profilefacts_and_passes_text():
    facts = ProfileFacts(contact=Contact(name="Ada"))
    agent = _FakeAgent(facts)
    result = extract_profile_facts("raw resume text", agent)
    assert result is facts
    assert agent.received == "raw resume text"


def test_extract_rejects_wrong_type():
    agent = _FakeAgent("not a ProfileFacts")
    with pytest.raises(TypeError):
        extract_profile_facts("x", agent)


def test_build_extractor_agent_is_configured(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    agent = build_extractor_agent(model_id="claude-haiku-4-5-20251001")
    assert isinstance(agent, AgentRunner)


def test_extractor_defaults_to_mid_tier(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    captured = {}

    import resume_agent.profile.extractor as extractor_mod

    def _fake_build_model(model_id, api_key=None, **kwargs):
        captured["id"] = model_id
        return object()

    class _FakeAgent:
        def __init__(self, **kwargs):
            pass

    monkeypatch.setattr(extractor_mod, "build_model", _fake_build_model)
    monkeypatch.setattr(extractor_mod, "Agent", _FakeAgent)

    extractor_mod.build_extractor_agent()
    assert captured["id"] == extractor_mod.get_settings().mid_model
