import asyncio
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

import resume_tailor_harness.llm_runner as llm_runner
from resume_tailor_harness.llm_runner import AgentRunner, is_transient


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


class _Schema(BaseModel):
    value: int


class _StructuredAgent:
    """An agent whose first N runs come back unparsed, as agno leaves them.

    agno does not raise when it cannot coerce a response into ``output_schema``
    -- it leaves ``RunOutput.content`` as the raw ``str`` on a run the provider
    reports as a success. Nothing in the transient-error path can see that, so a
    single malformed body used to go straight to the caller's fallback.
    """

    def __init__(self, unparsed: int):
        self.calls = 0
        self._unparsed = unparsed
        self.output_schema = _Schema

    def run(self, prompt):
        self.calls += 1
        if self.calls <= self._unparsed:
            return SimpleNamespace(content='{"value": 1')
        return SimpleNamespace(content=_Schema(value=1))

    async def arun(self, prompt):
        return self.run(prompt)


def test_unparsed_structured_output_is_retried():
    agent = _StructuredAgent(1)
    result = AgentRunner(agent).run("p")
    assert isinstance(result.content, _Schema)
    assert agent.calls == 2


def test_unparsed_structured_output_returns_last_response_when_exhausted():
    # Returned, never raised: the call site's own `expect_schema` owns the error,
    # and it carries model/status/token diagnostics this layer does not have.
    agent = _StructuredAgent(99)
    result = AgentRunner(agent).run("p")
    assert result.content == '{"value": 1'
    assert agent.calls == 3  # llm_retries default is 2


def test_arun_retries_unparsed_structured_output():
    agent = _StructuredAgent(1)
    result = asyncio.run(AgentRunner(agent).arun("p"))
    assert isinstance(result.content, _Schema)
    assert agent.calls == 2


def test_agent_without_output_schema_is_never_retried_for_content():
    # A free-text agent has no schema to miss, so prose must not look like a
    # failed parse -- that would retry every plain-text call.
    class _Prose:
        def __init__(self):
            self.calls = 0

        def run(self, prompt):
            self.calls += 1
            return SimpleNamespace(content="just prose")

    agent = _Prose()
    assert AgentRunner(agent).run("p").content == "just prose"
    assert agent.calls == 1
