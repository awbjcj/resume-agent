import pytest

from resume_tailor_harness.discovery.relevance import (
    RelevanceVerdict,
    compose_relevance_input,
    judge_relevance,
)


class _Result:
    def __init__(self, content):
        self.content = content


class _Agent:
    def __init__(self, verdict):
        self._verdict = verdict

    def run(self, prompt):
        return _Result(self._verdict)

    async def arun(self, prompt):
        return self.run(prompt)


def test_compose_input_includes_role_title_and_truncated_snippet():
    text = compose_relevance_input("AI roles", "CDL Driver", "x" * 1000)
    assert "AI roles" in text and "CDL Driver" in text
    assert text.count("x") <= 500


def test_judge_relevance_returns_verdict():
    agent = _Agent(RelevanceVerdict(keep=False, reason="trucking role"))
    verdict = judge_relevance("AI roles", "CDL Driver", "drive a truck", agent)
    assert verdict.keep is False and "trucking" in verdict.reason


def test_ajudge_relevance_uses_arun():
    import asyncio

    from resume_tailor_harness.discovery.relevance import ajudge_relevance

    class _AsyncAgent:
        def run(self, prompt):
            raise NotImplementedError

        async def arun(self, prompt):
            return _Result(RelevanceVerdict(keep=True, reason="ok"))

    out = asyncio.run(
        ajudge_relevance("target", "Eng", "jd", _AsyncAgent(), sem=asyncio.Semaphore(2))
    )
    assert isinstance(out, RelevanceVerdict) and out.keep is True


def test_judge_relevance_type_guard():
    with pytest.raises(TypeError):
        judge_relevance("AI roles", "T", "jd", _Agent("not a verdict"))


def test_build_relevance_agent_returns_none_without_api_key(monkeypatch):
    from resume_tailor_harness.discovery import relevance as mod

    class _Settings:
        cheap_model = "cheap"

    # No key configured for the resolved model's provider -> no agent.
    monkeypatch.setattr(mod, "get_settings", lambda: _Settings())
    monkeypatch.setattr(mod, "resolve_api_key", lambda model_id: "")
    assert mod.build_relevance_agent() is None
