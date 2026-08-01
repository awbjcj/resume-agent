from types import SimpleNamespace

import pytest
from agno.run.agent import RunEvent

from resume_agent.llm_runner import AgentRunner
from resume_agent.sessions.stream import (
    Completed,
    Failed,
    ReasoningDelta,
    TextDelta,
    ToolCompleted,
    ToolStarted,
)


class _Event:
    def __init__(self, event, **fields):
        self.event = event
        self.content = fields.pop("content", None)
        self.reasoning_content = fields.pop("reasoning_content", None)
        for key, value in fields.items():
            setattr(self, key, value)


class _Tool:
    def __init__(
        self,
        call_id: str,
        name: str,
        args=None,
        result=None,
        error=None,
    ):
        self.tool_call_id = call_id
        self.tool_name = name
        self.tool_args = args or {}
        self.result = result
        self.tool_call_error = error


class _Output:
    def __init__(self, content=""):
        self.content = content
        self.status = "COMPLETED"


class _FakeAgent:
    def __init__(self, attempts):
        self.attempts = list(attempts)
        self.calls = 0
        self.model = None

    def run(self, prompt, **kwargs):
        self.calls += 1
        assert kwargs == {
            "stream": True,
            "stream_events": True,
            "yield_run_output": True,
        }
        attempt = self.attempts.pop(0)

        def generate():
            for item in attempt:
                if isinstance(item, BaseException):
                    raise item
                yield item

        return generate()


class _Transient(Exception):
    status_code = 503


@pytest.fixture(autouse=True)
def _no_budget(monkeypatch):
    recorded = []
    monkeypatch.setattr(
        "resume_agent.tenancy.limits.enforce_agent_budget", lambda agent: None
    )
    monkeypatch.setattr(
        "resume_agent.tenancy.usage.record_call", lambda agent, response: recorded.append(response)
    )
    monkeypatch.setattr("resume_agent.llm_runner.refresh_agent_api_key", lambda agent: None)
    return recorded


def test_stream_maps_real_agno_content_enum_to_text_delta(_no_budget):
    output = _Output("final")
    agent = _FakeAgent(
        [[_Event(RunEvent.run_content, content="Hello"), output]]
    )

    events = list(AgentRunner(agent).stream("p"))

    assert events[0] == TextDelta("Hello")
    assert isinstance(events[-1], Completed)
    assert events[-1].response is output
    assert _no_budget == [output]


def test_reasoning_that_merely_echoes_the_visible_answer_is_not_reasoning():
    # agno's OpenAI Responses adapter copies output_text deltas into
    # reasoning_content whenever a reasoning config is sent without a summary.
    # We fix that at the request (build_model asks for a summary), but the seam
    # must not forward an echo either: duplicating the reply into the reasoning
    # channel alternates the two kinds on every delta, which flushes the sink
    # per token and renders one collapsible plus one markdown block per token.
    agent = _FakeAgent(
        [[
            _Event(RunEvent.run_content, content="Hello", reasoning_content="Hello"),
            _Event(RunEvent.run_content, content=" there", reasoning_content=" there"),
            _Output("Hello there"),
        ]]
    )

    events = list(AgentRunner(agent).stream("p"))

    assert [event for event in events if isinstance(event, ReasoningDelta)] == []
    assert [event for event in events if isinstance(event, TextDelta)] == [
        TextDelta("Hello"),
        TextDelta(" there"),
    ]


def test_genuine_reasoning_alongside_different_content_is_still_forwarded():
    agent = _FakeAgent(
        [[
            _Event(RunEvent.run_content, content="Yes.", reasoning_content="weighing it"),
            _Output("Yes."),
        ]]
    )

    events = list(AgentRunner(agent).stream("p"))

    assert ReasoningDelta("weighing it") in events
    assert TextDelta("Yes.") in events


def test_stream_maps_reasoning_and_tool_events_with_call_identity():
    tool = _Tool("call-7", "search_corpus", {"q": "Kafka"}, result="3 hits")
    agent = _FakeAgent(
        [[
            _Event(RunEvent.reasoning_content_delta, reasoning_content="because"),
            _Event(RunEvent.tool_call_started, tool=tool),
            _Event(RunEvent.tool_call_completed, tool=tool),
            _Output("final"),
        ]]
    )

    events = list(AgentRunner(agent).stream("p"))

    assert ReasoningDelta("because") in events
    assert ToolStarted("call-7", "search_corpus", "{'q': 'Kafka'}") in events
    assert ToolCompleted("call-7", "search_corpus", "3 hits", True) in events


def test_tool_error_uses_event_error_and_marks_completion_not_ok():
    tool = _Tool("call-2", "probe")
    agent = _FakeAgent(
        [[
            _Event(RunEvent.tool_call_error, tool=tool, error="boom"),
            _Output("final"),
        ]]
    )

    events = list(AgentRunner(agent).stream("p"))

    assert ToolCompleted("call-2", "probe", "boom", False) in events


def test_run_error_event_is_terminal_and_not_followed_by_completed():
    agent = _FakeAgent(
        [[_Event(RunEvent.run_error, content="provider said no", error_type="Bad")]]
    )

    events = list(AgentRunner(agent).stream("p"))

    assert events == [Failed("provider said no", "Bad")]


def test_transient_failure_before_visible_output_retries(monkeypatch):
    monkeypatch.setattr(
        "resume_agent.llm_runner.get_settings", lambda: _settings(retries=1)
    )
    output = _Output("final")
    agent = _FakeAgent([[_Transient("busy")], [_Event(RunEvent.run_content, content="hi"), output]])

    events = list(AgentRunner(agent).stream("p"))

    assert agent.calls == 2
    assert TextDelta("hi") in events
    assert isinstance(events[-1], Completed)


def test_transient_failure_after_visible_output_does_not_retry(monkeypatch):
    monkeypatch.setattr(
        "resume_agent.llm_runner.get_settings", lambda: _settings(retries=3)
    )
    agent = _FakeAgent(
        [[_Event(RunEvent.run_content, content="hi"), _Transient("lost")]]
    )

    events = list(AgentRunner(agent).stream("p"))

    assert agent.calls == 1
    assert events[0] == TextDelta("hi")
    assert events[-1] == Failed("lost", "_Transient")


def test_ignored_lifecycle_event_does_not_prevent_pre_output_retry(monkeypatch):
    monkeypatch.setattr(
        "resume_agent.llm_runner.get_settings", lambda: _settings(retries=1)
    )
    output = _Output("final")
    agent = _FakeAgent(
        [
            [_Event(RunEvent.run_started), _Transient("busy")],
            [_Event(RunEvent.run_content, content="ok"), output],
        ]
    )

    events = list(AgentRunner(agent).stream("p"))

    assert agent.calls == 2
    assert TextDelta("ok") in events


def test_stream_terminal_error_status_yields_failed_not_completed(_no_budget):
    output = _Output("provider rejected the request")
    output.status = "ERROR"
    agent = _FakeAgent([[_Event(RunEvent.run_content, content="partial"), output]])

    events = list(AgentRunner(agent).stream("p"))

    assert TextDelta("partial") in events
    assert isinstance(events[-1], Failed)
    assert events[-1].message == "provider rejected the request"
    assert events[-1].code == "RUN_ERROR"
    assert not any(isinstance(event, Completed) for event in events)
    assert _no_budget == [output]


def test_stream_without_terminal_run_output_fails_closed():
    agent = _FakeAgent([[_Event(RunEvent.run_completed)]])

    events = list(AgentRunner(agent).stream("p"))

    assert isinstance(events[-1], Failed)
    assert events[-1].code == "MISSING_RUN_OUTPUT"


def _settings(retries: int):
    return SimpleNamespace(llm_retries=retries, llm_retry_delay=0.0)
