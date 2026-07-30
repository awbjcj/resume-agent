import warnings

import pytest
from pydantic import BaseModel

from resume_agent.llm_runner import build_model, resolve_api_key, split_provider
from resume_agent.models.resume import ResumeContent


def test_split_provider_bare_id_defaults_anthropic():
    assert split_provider("claude-opus-4-8") == ("anthropic", "claude-opus-4-8")


@pytest.mark.parametrize(
    "model_id,expected",
    [
        ("openai:gpt-5.4-mini", ("openai", "gpt-5.4-mini")),
        ("gemini:gemini-2.0-flash", ("gemini", "gemini-2.0-flash")),
        ("deepseek:deepseek-chat", ("deepseek", "deepseek-chat")),
    ],
)
def test_split_provider_parses_known_prefixes(model_id, expected):
    assert split_provider(model_id) == expected


def test_split_provider_unknown_prefix_stays_anthropic():
    # A Workday-style "tenant:site" is never a model id; it must not be mistaken
    # for a provider, so it passes through whole as an Anthropic id.
    assert split_provider("tenant:site") == ("anthropic", "tenant:site")


def test_resolve_api_key_reads_provider_specific_setting(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ak")
    monkeypatch.setenv("OPENAI_API_KEY", "ok")
    monkeypatch.setenv("GEMINI_API_KEY", "gk")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "dk")
    from resume_agent.config import env_settings

    env_settings.cache_clear()
    assert resolve_api_key("claude-opus-4-8") == "ak"
    assert resolve_api_key("openai:gpt-5.4-mini") == "ok"
    assert resolve_api_key("gemini:gemini-2.0-flash") == "gk"
    assert resolve_api_key("deepseek:deepseek-chat") == "dk"
    env_settings.cache_clear()


def test_build_model_anthropic_branch():
    from agno.models.anthropic import Claude

    model = build_model("claude-opus-4-8", api_key="sk-test")
    assert isinstance(model, Claude)
    assert model.id == "claude-opus-4-8"
    assert model.api_key == "sk-test"


def test_build_model_sets_cache_system_prompt_for_anthropic():
    model = build_model("claude-test", api_key="sk-test", cache_system_prompt=True)
    assert model.cache_system_prompt is True


def test_build_model_cache_defaults_off_and_other_providers_ignore_it():
    assert build_model("claude-test", api_key="sk-test").cache_system_prompt is False
    assert (
        build_model("openai:gpt-test", api_key="sk-test", cache_system_prompt=True).id
        == "gpt-test"
    )


def test_build_model_openai_branch():
    OpenAIResponses = pytest.importorskip(
        "agno.models.openai.responses"
    ).OpenAIResponses
    model = build_model("openai:gpt-5.4-mini", api_key="sk-test")
    assert isinstance(model, OpenAIResponses)
    assert model.id == "gpt-5.4-mini"
    assert model.api_key == "sk-test"


def test_build_model_gemini_branch():
    Gemini = pytest.importorskip("agno.models.google").Gemini
    model = build_model("gemini:gemini-2.0-flash", api_key="sk-test")
    assert isinstance(model, Gemini)
    assert model.id == "gemini-2.0-flash"


def test_build_model_gemini_3_never_sends_thinking_budget():
    # Verified live against gemini-3.6-flash: thinking_budget=0 fails the WHOLE
    # request with 400 INVALID_ARGUMENT, generating nothing (in=0/out=0 tokens),
    # and agno surfaces that error body as a plain str. Gemini 3 replaced the
    # budget with thinking_level, so a non-reasoning agent bounds thinking with
    # "low" -- which reports thoughts=None -- and never with a budget.
    model = build_model("gemini:gemini-3.6-flash", api_key="sk-test")
    assert model.thinking_budget is None
    assert model.thinking_level == "low"


def test_build_model_gemini_3_uses_high_thinking_level_when_reasoning():
    model = build_model("gemini:gemini-3.5-flash", api_key="sk-test", reasoning=True)
    assert model.thinking_budget is None
    assert model.thinking_level == "high"


def test_build_model_pre_gemini_3_still_disables_thinking_with_a_budget():
    # Older Gemini ids have no thinking_level and treat an unset thinking config
    # as "provider decides" (unbounded automatic budget) rather than off, so 0
    # remains the way to disable it there. Reachable in practice: gemini-2.5-*
    # is still a current model a user can enter in the custom tier field (only
    # gemini-2.0 and older are deprecated).
    model = build_model("gemini:gemini-2.0-flash", api_key="sk-test")
    assert model.thinking_budget == 0
    assert model.thinking_level is None


def test_build_model_pre_gemini_3_never_sends_thinking_level_when_reasoning():
    # The mirror image of the thinking_budget-on-Gemini-3 failure: pre-3 ids have
    # no thinking_level, and agno forwards any non-None value straight into
    # ThinkingConfig, so sending one would 400 the whole request and come back as
    # a plain str. Reasoning is left to the provider's own budget instead.
    model = build_model("gemini:gemini-2.5-flash", api_key="sk-test", reasoning=True)
    assert model.thinking_level is None
    assert model.thinking_budget is None


def test_openai_response_schema_has_no_keywords_beside_refs():
    model = build_model("openai:gpt-5.6-terra", api_key="sk-test")

    params = model.get_request_params(response_format=ResumeContent)
    schema = params["text"]["format"]["schema"]

    assert schema["$defs"]["Education"]["properties"]["source"] == {
        "$ref": "#/$defs/Source"
    }
    assert schema["$defs"]["Language"]["properties"]["source"] == {
        "$ref": "#/$defs/Source"
    }


def test_gemini_uses_json_schema_without_lossy_dictionary_placeholder():
    model = build_model("gemini:gemini-3.6-flash", api_key="sk-test")

    params = model.get_request_params(response_format=ResumeContent)
    config = params["config"]
    skills_schema = config.response_json_schema["properties"]["skills"]

    assert config.response_schema is None
    assert "example_key" not in skills_schema.get("properties", {})
    assert skills_schema["additionalProperties"]["items"] == {
        "$ref": "#/$defs/TailoredSkill"
    }
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        config.model_dump()
    assert not [
        warning
        for warning in caught
        if "PydanticSerializationUnexpectedValue" in str(warning.message)
    ]


def test_claude_falls_back_to_json_mode_only_for_oversized_schema():
    from resume_agent.llm_runner import use_json_mode_for

    class SmallOutput(BaseModel):
        answer: str

    model = build_model("claude-sonnet-5", api_key="sk-test")

    assert use_json_mode_for(model, SmallOutput) is False
    assert use_json_mode_for(model, ResumeContent) is True


def test_build_model_deepseek_branch():
    DeepSeek = pytest.importorskip("agno.models.deepseek").DeepSeek
    model = build_model("deepseek:deepseek-chat", api_key="sk-test")
    assert isinstance(model, DeepSeek)
    assert model.id == "deepseek-chat"


def test_agent_runner_arun_delegates():
    import asyncio

    from resume_agent.llm_runner import AgentRunner

    class _AsyncAgent:
        async def arun(self, prompt):
            return f"got {prompt}"

    out = asyncio.run(AgentRunner(_AsyncAgent()).arun("hi"))
    assert out == "got hi"


def test_agent_runner_closes_cached_sdk_client_inside_active_loop():
    import asyncio
    from dataclasses import dataclass

    from resume_agent.llm_runner import AgentRunner

    class _AsyncClient:
        def __init__(self):
            self.closed = False
            self.loop_was_running = False

        async def close(self):
            self.loop_was_running = asyncio.get_running_loop().is_running()
            self.closed = True

    @dataclass
    class _Model:
        async_client: _AsyncClient | None

    @dataclass
    class _Agent:
        model: _Model

    client = _AsyncClient()
    model = _Model(async_client=client)
    agent = _Agent(model=model)

    asyncio.run(AgentRunner(agent).aclose())

    assert client.closed is True
    assert client.loop_was_running is True
    assert model.async_client is None


def test_run_with_cleanup_closes_runner_when_operation_raises():
    import asyncio

    from resume_agent import llm_runner

    class _Runner:
        def __init__(self):
            self.closed = False

        async def aclose(self):
            self.closed = True

    runner = _Runner()

    async def fail():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(llm_runner.run_with_cleanup(fail(), runner))

    assert runner.closed is True


def test_run_with_cleanup_preserves_result_and_closes_remaining_runners_after_cleanup_error():
    import asyncio

    from resume_agent import llm_runner

    class _BrokenRunner:
        async def aclose(self):
            raise RuntimeError("close failed")

    class _GoodRunner:
        def __init__(self):
            self.closed = False

        async def aclose(self):
            self.closed = True

    async def succeed():
        return "ok"

    good = _GoodRunner()
    result = asyncio.run(llm_runner.run_with_cleanup(succeed(), _BrokenRunner(), good))

    assert result == "ok"
    assert good.closed is True


def test_acall_respects_semaphore_limit():
    import asyncio

    from resume_agent.concurrency import gather_isolated
    from resume_agent.llm_runner import acall

    state = {"now": 0, "max": 0}

    class _Result:
        def __init__(self, content):
            self.content = content

    class _Agent:
        def run(self, prompt):
            return _Result(prompt)

        async def arun(self, prompt):
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
            await asyncio.sleep(0.02)
            state["now"] -= 1
            return _Result(prompt)

    async def go():
        sem = asyncio.Semaphore(2)
        return await gather_isolated(
            range(6), lambda i: acall(_Agent(), str(i), sem=sem)
        )

    results = asyncio.run(go())
    assert state["max"] <= 2
    assert all(r.ok for r in results)


def test_acall_observes_permit_release_after_error():
    import asyncio

    from resume_agent.llm_runner import acall

    events: list[str] = []

    class _Agent:
        def run(self, prompt):
            return prompt

        async def arun(self, prompt):
            raise RuntimeError("boom")

    async def go():
        with pytest.raises(RuntimeError, match="boom"):
            await acall(
                _Agent(),
                "prompt",
                sem=asyncio.Semaphore(1),
                on_acquire=lambda: events.append("acquire"),
                on_release=lambda: events.append("release"),
            )

    asyncio.run(go())
    assert events == ["acquire", "release"]


def test_retry_kwargs_disables_agno_retry_regardless_of_settings(monkeypatch):
    # Retries live in AgentRunner behind is_transient now; agno's own retry is
    # always off, independent of llm_retries/llm_retry_delay.
    monkeypatch.setenv("LLM_RETRIES", "5")
    monkeypatch.setenv("LLM_RETRY_DELAY", "3")
    from resume_agent.config import env_settings
    from resume_agent.llm_runner import retry_kwargs

    env_settings.cache_clear()
    try:
        assert retry_kwargs() == {"retries": 0}
    finally:
        env_settings.cache_clear()


def test_tool_kwargs_bounds_tool_loop():
    from resume_agent.llm_runner import tool_kwargs

    assert tool_kwargs() == {"tool_call_limit": 15}


# --- Unparsed structured output diagnostics -------------------------------
#
# agno leaves RunOutput.content as the raw str when it cannot parse a response
# into output_schema. Every call site used to raise a bare TypeError naming only
# the type, which destroyed the one piece of evidence that says WHY (truncated
# vs refusal vs rejected schema). These pin the diagnostics onto the exception.


class _Metrics:
    def __init__(self, input_tokens=0, output_tokens=0, reasoning_tokens=0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.reasoning_tokens = reasoning_tokens


class _RunOutput:
    def __init__(
        self, content, *, model=None, model_provider=None, metrics=None, status=None
    ):
        self.content = content
        self.model = model
        self.model_provider = model_provider
        self.metrics = metrics
        self.status = status


def test_expect_schema_returns_content_when_it_already_matches():
    from resume_agent.llm_runner import expect_schema
    from resume_agent.models.profile import Contact

    content = ResumeContent(contact=Contact(name="Ada"))
    assert expect_schema(_RunOutput(content), ResumeContent, source="tailor") is content


def test_unparsed_output_keeps_the_tail_so_truncation_is_visible():
    # A response cut off by an output-token ceiling ends mid-JSON. Only the TAIL
    # shows that, so the preview must never be head-only.
    from resume_agent.llm_runner import UnparsedAgentOutput, expect_schema

    truncated = '{"contact": {"name": "Ada"}, "experience": [{"company": "Acme' + (
        "x" * 5000
    )
    with pytest.raises(UnparsedAgentOutput) as excinfo:
        expect_schema(
            _RunOutput(
                truncated,
                model="gemini-3.5-flash",
                model_provider="Google",
                metrics=_Metrics(input_tokens=12000, output_tokens=8192, reasoning_tokens=7900),
            ),
            ResumeContent,
            source="tailor",
        )
    message = str(excinfo.value)
    assert "ResumeContent" in message
    assert "tailor" in message
    assert "gemini-3.5-flash" in message
    assert "Google" in message
    assert f"chars={len(truncated)}" in message
    assert '{"contact"' in message  # head survives
    assert message.rstrip().endswith("xxx")  # tail survives
    # reasoning_tokens is how we can tell whether thinking was actually disabled
    assert "reasoning=7900" in message
    assert "out=8192" in message


def test_unparsed_output_is_still_a_type_error():
    # Callers and existing tests catch TypeError; widening the diagnostics must
    # not change what propagates through gather_isolated.
    from resume_agent.llm_runner import UnparsedAgentOutput, expect_schema

    with pytest.raises(TypeError):
        expect_schema(_RunOutput("nope"), ResumeContent, source="tailor")
    assert issubclass(UnparsedAgentOutput, TypeError)


def test_unparsed_output_survives_a_result_without_metadata():
    # RunOutput shape drifts between agno versions; diagnostics must degrade,
    # never mask the failure they are describing.
    from resume_agent.llm_runner import UnparsedAgentOutput, expect_schema

    class _Bare:
        content = ""

    with pytest.raises(UnparsedAgentOutput) as excinfo:
        expect_schema(_Bare(), ResumeContent, source="reviser")
    assert "chars=0" in str(excinfo.value)


def test_expect_text_returns_content_for_a_completed_run():
    from resume_agent.llm_runner import expect_text

    assert expect_text(_RunOutput("coach notes"), source="coach notes") == "coach notes"


def test_expect_text_rejects_an_errored_run_whose_content_is_the_error_body():
    # agno does not raise when a provider rejects a request: it sets status to
    # ERROR and -- because content was still None -- assigns the provider's
    # error body to content as a plain str. A structured call site notices
    # because the body is not the schema; a free-text one cannot tell an error
    # body from a real answer. That is how a hard 400 ("Function tools with
    # reasoning_effort are not supported ...") reached the coach formatter
    # dressed as coach notes and surfaced two layers downstream as the
    # nonsensical "opening turn proposed no topics".
    from resume_agent.llm_runner import UnparsedAgentOutput, expect_text

    errored = _RunOutput(
        "Function tools with reasoning_effort are not supported for "
        "gpt-5.6-terra in /v1/chat/completions.",
        status="ERROR",
        model="gpt-5.6-terra",
        model_provider="OpenAI",
    )
    with pytest.raises(UnparsedAgentOutput) as excinfo:
        expect_text(errored, source="coach notes")
    message = str(excinfo.value)
    assert "coach notes" in message
    assert "reasoning_effort" in message
    assert "OpenAI" in message


def test_expect_text_rejects_blank_and_non_text_content():
    # Blank notes are as unusable as an error body, and a non-str content means
    # the run did not produce prose at all.
    from resume_agent.llm_runner import UnparsedAgentOutput, expect_text

    with pytest.raises(UnparsedAgentOutput):
        expect_text(_RunOutput("   "), source="coach notes")
    with pytest.raises(UnparsedAgentOutput):
        expect_text(_RunOutput(None), source="coach notes")
