import pytest

from agno.agent import Agent

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
    assert isinstance(agent, Agent)
