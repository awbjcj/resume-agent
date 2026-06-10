import pytest

from resume_agent.llm_runner import AgentRunner

from resume_agent.models.job import JobCriteria, SponsorshipSignal
from resume_agent.discovery.extract import build_extract_agent, extract_job_criteria


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


def test_extract_returns_criteria_and_passes_text():
    criteria = JobCriteria(sponsorship_signal=SponsorshipSignal.offered)
    agent = _FakeAgent(criteria)
    out = extract_job_criteria("jd text", agent)
    assert out is criteria
    assert agent.received == "jd text"


def test_extract_rejects_wrong_type():
    with pytest.raises(TypeError):
        extract_job_criteria("x", _FakeAgent("nope"))


def test_build_extract_agent_is_agent(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert isinstance(build_extract_agent(model_id="claude-haiku-4-5-20251001"), AgentRunner)
