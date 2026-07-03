import asyncio

import pytest

import resume_agent.llm_runner as llm_runner
from resume_agent.llm_runner import AgentRunner, is_transient


class _TransientError(Exception):
    status_code = 429


class _FlakyAgent:
    def __init__(self, failures: int, exc: Exception):
        self.calls = 0
        self._failures = failures
        self._exc = exc

    def run(self, prompt):
        self.calls += 1
        if self.calls <= self._failures:
            raise self._exc
        return "ok"

    async def arun(self, prompt):
        return self.run(prompt)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(llm_runner.time, "sleep", lambda s: None)

    async def _instant(_s):
        return None

    monkeypatch.setattr(llm_runner.asyncio, "sleep", _instant)


def test_transient_failure_is_retried():
    agent = _FlakyAgent(1, _TransientError())
    assert AgentRunner(agent).run("p") == "ok"
    assert agent.calls == 2


def test_permanent_failure_surfaces_immediately():
    agent = _FlakyAgent(5, ValueError("schema mismatch"))
    with pytest.raises(ValueError):
        AgentRunner(agent).run("p")
    assert agent.calls == 1


def test_transient_failure_exhausts_then_raises():
    agent = _FlakyAgent(99, _TransientError())
    with pytest.raises(_TransientError):
        AgentRunner(agent).run("p")
    assert agent.calls >= 2  # llm_retries default is 2 -> 3 calls


def test_arun_retries_transient_failures():
    agent = _FlakyAgent(1, _TransientError())
    assert asyncio.run(AgentRunner(agent).arun("p")) == "ok"
    assert agent.calls == 2


def test_is_transient_predicate():
    assert is_transient(_TransientError())
    assert not is_transient(ValueError("bad output"))

    class _NamedLikeSdk(Exception):
        pass

    _NamedLikeSdk.__name__ = "RateLimitError"
    assert is_transient(_NamedLikeSdk())


def test_retry_kwargs_disables_agno_retry():
    assert llm_runner.retry_kwargs() == {"retries": 0}
