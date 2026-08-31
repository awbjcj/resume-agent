from types import SimpleNamespace
from typing import cast

from agno.models.message import Message
from openai.types.responses import Response, ResponseStreamEvent
import pytest
from pydantic import BaseModel

import resume_tailor_harness.llm_runner as llm_runner
from resume_tailor_harness.llm_runner import (
    anthropic_version,
    anthropic_web_search_tool,
    build_model,
    provider_capabilities,
)


def test_reasoning_parameters_are_attached_for_capable_models():
    claude = build_model("claude-sonnet-5", api_key="k", reasoning=True)
    assert claude.thinking == {"type": "adaptive"}
    assert claude.output_config == {"effort": "high"}

    openai = build_model("openai:gpt-5.6-terra", api_key="k", reasoning=True)
    assert openai.reasoning == {"effort": "high"}

    gemini = build_model("gemini:gemini-3.5-flash", api_key="k", reasoning=True)
    assert gemini.thinking_level == "high"

    deepseek = build_model("deepseek:deepseek-v4-pro", api_key="k", reasoning=True)
    assert deepseek.reasoning == {"effort": "max"}


def test_builder_refuses_reasoning_for_incapable_model():
    haiku = build_model("claude-haiku-4-5-20251001", api_key="k", reasoning=True)
    assert haiku.thinking is None
    assert haiku.output_config is None


def test_non_reasoning_claude_disables_thinking_rather_than_omitting_it():
    # Omitting `thinking` runs ADAPTIVE on Sonnet 5 -- the default mid_model -- so
    # an unset config bought thinking on every writer/reviser agent, and thinking
    # shares max_tokens with the response text. Same class of bug as sending
    # thinking_budget to Gemini 3: the request looks fine and the JSON comes back
    # truncated, surfacing as UnparsedAgentOutput rather than an HTTP error.
    sonnet = build_model("claude-sonnet-5", api_key="k")
    assert sonnet.thinking == {"type": "disabled"}
    assert sonnet.output_config is None


def test_openai_asks_for_a_reasoning_summary_whenever_it_sends_a_reasoning_config():
    # agno's Responses adapter copies every output_text delta into
    # reasoning_content when `reasoning` is set and `reasoning_summary` is not:
    #
    #     if self.reasoning is not None and self.reasoning_summary is None:
    #         model_response.reasoning_content = stream_event.delta
    #
    # Since a catalogued id always gets an explicit effort (even "none"), that
    # fired on EVERY OpenAI agent -- the visible answer was duplicated into the
    # reasoning channel token by token, so the coach thread rendered one
    # collapsible and one markdown block per token. Verified live: with a
    # summary requested the duplication drops to zero at every effort, and a
    # genuinely reasoning call streams real summaries instead of an echo.
    for reasoning in (False, True):
        model = build_model("openai:gpt-5.6-terra", api_key="k", reasoning=reasoning)
        assert model.reasoning is not None
        assert model.reasoning_summary == "auto"

    # An uncatalogued id sends no reasoning config at all -- its effort
    # vocabulary is unknown -- so it must not ask for a summary either.
    unknown = build_model("openai:gpt-experimental-preview", api_key="k")
    assert unknown.reasoning is None
    assert unknown.reasoning_summary is None


def test_non_reasoning_deepseek_disables_thinking_rather_than_omitting_it():
    # Fourth instance of the "unset means provider decides" trap, after Gemini,
    # Anthropic and OpenAI. Verified live: omitting `reasoning` entirely on
    # deepseek-v4-flash spent 46 reasoning tokens and emitted a reasoning output
    # item, so an unset config bought thinking on every non-reasoning agent.
    #
    # On the Responses API `reasoning.effort` is BOTH the toggle and the dial --
    # `none` disables thinking outright (verified: zero reasoning tokens, no
    # reasoning output item) -- so the Chat Completions
    # `extra_body={"thinking": {"type": "disabled"}}` side-channel is gone.
    for model_id in ("deepseek:deepseek-v4-pro", "deepseek:deepseek-v4-flash"):
        model = build_model(model_id, api_key="k")
        assert model.reasoning == {"effort": "none"}, model_id
        assert model.get_request_params()["reasoning"] == {
            "effort": "none",
            "summary": "auto",
        }, model_id


def test_deepseek_rides_the_responses_api_under_its_own_provider_name():
    # `tenancy.costs.normalize_provider` tests for "openai" BEFORE "deepseek", so
    # a subclass of the OpenAI Responses adapter that inherited provider="OpenAI"
    # would bill every DeepSeek call to the OpenAI budget, resolve the OpenAI key,
    # and report `openai:deepseek-...` from `_agent_model_id`.
    from resume_tailor_harness.tenancy.costs import normalize_provider

    model = build_model("deepseek:deepseek-v4-flash", api_key="k")
    assert model.provider == "DeepSeek"
    assert normalize_provider(model.provider) == "deepseek"
    assert model.base_url == "https://api.deepseek.com"
    assert model.id == "deepseek-v4-flash"


def test_deepseek_sends_the_unmodified_schema_without_strict():
    # DeepSeek's `strict` gates validation of the REQUEST SCHEMA, not constrained
    # decoding of the response -- unlike OpenAI, where a strict schema compiles to
    # a grammar that makes a stray key or a wrong-typed field impossible to emit.
    # Measured against instructions that deliberately violate the schema:
    # strict=True still returned a wrong-typed field 6/6 and leaked an undeclared
    # key 5/6 (strict=False: 6/6 and 6/6). It enforces nothing.
    #
    # So the only thing strict=True would buy is its own precondition: a sibling
    # `type` on every bare `anyOf` -- which for a nullable OBJECT can only be the
    # false value `null`, because DeepSeek rejects `object`. Measured across
    # FitScore and JobCriteriaExtract at n=10 per arm, that rewrite was
    # indistinguishable from sending the raw schema (10/10 valid, and 10/10
    # populated on every nullable-object field, either way).
    class Inner(BaseModel):
        city: str

    class Outer(BaseModel):
        name: str | None
        place: Inner | None

    model = build_model("deepseek:deepseek-v4-flash", api_key="k")
    params = model.get_request_params(response_format=Outer)
    text_format = params["text"]["format"]

    assert text_format["strict"] is False
    # Untouched: both the scalar union and the $ref union keep the bare `anyOf`
    # pydantic emitted. A normalizer would also carry a latent gap -- a union of
    # two models with no null member yields no legal scalar sibling and would 400.
    unions = [
        node
        for node in llm_runner._walk_json_schema(text_format["schema"])
        if isinstance(node.get("anyOf"), list)
    ]
    assert len(unions) == 2
    assert all("type" not in node for node in unions)


def test_pre_4_6_claude_omits_thinking_instead_of_disabling_it():
    # On that generation an unset config already means no thinking, and agno
    # rejects a thinking config outright on the Haiku 3/3.5 families.
    assert build_model("claude-3-5-haiku-20241022", api_key="k").thinking is None
    assert build_model("claude-sonnet-4-5-20250929", api_key="k").thinking is None


def test_claude_bounds_max_tokens_above_agno_default():
    # agno defaults to 8192 for thinking + response combined, which truncates a
    # full ResumeContent and starves a scout's tool loop.
    assert build_model("claude-sonnet-5", api_key="k").max_tokens == 16000
    assert build_model("claude-opus-5", api_key="k", reasoning=True).max_tokens == 32000


def test_claude_max_tokens_respects_the_sdk_non_streaming_ceiling():
    # These calls are non-streaming and the SDK raises ValueError above a
    # per-model ceiling, so a custom Opus 4.1 id must clamp rather than blow up.
    assert build_model("claude-opus-4-1-20250805", api_key="k").max_tokens == 8192


def test_anthropic_version_treats_pre_4_ids_as_legacy():
    assert anthropic_version("claude-sonnet-5") == (5, 0)
    assert anthropic_version("claude-opus-4-8") == (4, 8)
    assert anthropic_version("claude-haiku-4-5-20251001") == (4, 5)
    # Pre-4 ids put the version before the family and must not read as modern.
    assert anthropic_version("claude-3-5-haiku-20241022") is None
    assert anthropic_version("claude-3-7-sonnet-20250219") is None


def test_reasoning_is_gated_on_generation_not_on_the_word_haiku():
    # Adaptive thinking and output_config.effort both arrived with 4.6; a pre-4.6
    # id reachable through the tier picker's custom field would 400 at runtime,
    # and agno's own NON_THINKING_MODELS guard only covers Haiku 3 and 3.5.
    assert provider_capabilities("claude-sonnet-5").supports_reasoning is True
    assert provider_capabilities("claude-opus-4-6").supports_reasoning is True
    assert (
        provider_capabilities("claude-sonnet-4-5-20250929").supports_reasoning is False
    )
    assert provider_capabilities("claude-opus-4-5").supports_reasoning is False
    assert provider_capabilities("claude-haiku-4-5").supports_reasoning is False


def test_web_search_tool_version_is_gated_on_generation():
    # web_search_20260209 requires 4.6+; older ids need the basic type or the
    # Messages API rejects the tool definition before any search runs.
    assert anthropic_web_search_tool("claude-sonnet-5")["type"] == "web_search_20260209"
    assert anthropic_web_search_tool("claude-opus-5")["type"] == "web_search_20260209"
    for legacy in ("claude-haiku-4-5", "claude-sonnet-4-5-20250929", "claude-opus-4-5"):
        assert anthropic_web_search_tool(legacy)["type"] == "web_search_20250305"


def test_anthropic_cache_flag_is_forwarded():
    model = build_model("claude-sonnet-5", api_key="k", cache_system_prompt=True)
    assert model.cache_system_prompt is True


def test_selected_tier_tuning_is_forwarded_by_provider(monkeypatch):
    settings = SimpleNamespace(
        cheap_model="gemini:gemini-3.5-flash",
        cheap_reasoning_effort="minimal",
        mid_model="claude-sonnet-5",
        mid_reasoning_effort="low",
        premium_model="openai:gpt-5.5",
        premium_reasoning_effort="xhigh",
    )
    monkeypatch.setattr(llm_runner, "get_settings", lambda: settings)

    claude = build_model("claude-sonnet-5", api_key="k", reasoning=True)
    openai = build_model("openai:gpt-5.5", api_key="k", reasoning=True)
    gemini = build_model("gemini:gemini-3.5-flash", api_key="k", reasoning=True)

    assert claude.output_config == {"effort": "low"}
    assert openai.reasoning == {"effort": "xhigh"}
    assert gemini.thinking_level == "minimal"


def test_openai_agents_are_built_on_the_responses_endpoint():
    from agno.models.openai.responses import OpenAIResponses

    model = build_model("openai:gpt-5.6-terra", api_key="k")
    assert isinstance(model, OpenAIResponses)
    assert model.id == "gpt-5.6-terra"


def test_openai_reasoning_and_function_tools_share_the_same_request(monkeypatch):
    settings = SimpleNamespace(
        cheap_model=None,
        cheap_reasoning_effort=None,
        mid_model=None,
        mid_reasoning_effort=None,
        premium_model=None,
        premium_reasoning_effort=None,
    )
    monkeypatch.setattr(llm_runner, "get_settings", lambda: settings)

    model = build_model("openai:gpt-5.5-pro", api_key="k", reasoning=True)
    params = model.get_request_params(
        messages=[],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "lookup_profile",
                    "description": "Look up a profile",
                    "parameters": {
                        "type": "object",
                        "properties": {},
                        "required": [],
                        "additionalProperties": False,
                    },
                },
            }
        ],
    )

    # The summary rides along because it is what stops agno relabelling the
    # visible answer as reasoning; search-equipped agents go through the same
    # builder, so they inherit it.
    assert params["reasoning"] == {"effort": "high", "summary": "auto"}
    assert params["tools"][0]["name"] == "lookup_profile"
    assert not hasattr(llm_runner, "_openai_disabled_effort")


def test_openai_non_reasoning_effort_uses_the_catalog_floor():
    assert build_model("openai:gpt-5.5-pro", api_key="k").reasoning == {
        "effort": "medium"
    }
    assert build_model("openai:gpt-5.6-terra", api_key="k").reasoning == {
        "effort": "none"
    }


def test_openai_uncatalogued_model_sends_no_reasoning_at_all():
    custom = build_model("openai:gpt-5.9-experimental", api_key="k")
    assert custom.reasoning is None
    assert "reasoning" not in custom.get_request_params(messages=[])


def test_openai_never_uses_provider_managed_response_state():
    model = build_model("openai:gpt-5.6-terra", api_key="k")
    assert model.store is False
    params = model.get_request_params(messages=[])
    assert params["store"] is False
    assert params["include"] == ["reasoning.encrypted_content"]


def test_openai_bounds_the_output_budget():
    # Bounded, but not with Anthropic's number. `_anthropic_max_tokens` stays
    # near 16000 because the SDK enforces a per-model non-streaming ceiling;
    # the Responses API has no such rule, so copying that figure here rationed
    # legitimate output and truncated large structured responses. The reasoning
    # budget is the larger one because on OpenAI -- unlike Anthropic -- thinking
    # tokens are spent out of this same allowance.
    assert build_model("openai:gpt-5.6-terra", api_key="k").max_output_tokens == 32000
    assert (
        build_model(
            "openai:gpt-5.6-terra", api_key="k", reasoning=True
        ).max_output_tokens
        == 64000
    )


def test_openai_effort_floor_is_the_lowest_effort_the_model_declares():
    assert (
        llm_runner._responses_effort("openai:gpt-5.6-terra", "openai", reasoning=False)
        == "none"
    )
    assert (
        llm_runner._responses_effort("openai:gpt-5.4-mini", "openai", reasoning=False)
        == "none"
    )
    assert (
        llm_runner._responses_effort("openai:gpt-5.5-pro", "openai", reasoning=False)
        == "medium"
    )


def test_openai_effort_is_unset_for_an_uncatalogued_model():
    model_id = "openai:gpt-5.9-experimental"
    assert llm_runner._responses_effort(model_id, "openai", reasoning=False) is None
    assert llm_runner._responses_effort(model_id, "openai", reasoning=True) is None


def test_openai_reasoning_effort_defaults_to_high_within_the_catalog(monkeypatch):
    settings = SimpleNamespace(
        cheap_model=None,
        cheap_reasoning_effort=None,
        mid_model=None,
        mid_reasoning_effort=None,
        premium_model=None,
        premium_reasoning_effort=None,
    )
    monkeypatch.setattr(llm_runner, "get_settings", lambda: settings)

    assert (
        llm_runner._responses_effort("openai:gpt-5.6-terra", "openai", reasoning=True)
        == "high"
    )
    assert (
        llm_runner._responses_effort("openai:gpt-5.5-pro", "openai", reasoning=True)
        == "high"
    )


def test_openai_reasoning_effort_honours_configured_tier_tuning(monkeypatch):
    settings = SimpleNamespace(
        cheap_model=None,
        cheap_reasoning_effort=None,
        mid_model=None,
        mid_reasoning_effort=None,
        premium_model="openai:gpt-5.6-terra",
        premium_reasoning_effort="max",
    )
    monkeypatch.setattr(llm_runner, "get_settings", lambda: settings)

    assert (
        llm_runner._responses_effort("openai:gpt-5.6-terra", "openai", reasoning=True)
        == "max"
    )


def test_openai_effort_ordering_covers_every_catalogued_value():
    for entry in llm_runner.MODEL_CATALOG["openai"]:
        for effort in entry.reasoning_efforts:
            assert effort in llm_runner._EFFORT_ORDER


def test_openai_reasoning_fallback_uses_the_nearest_supported_effort(monkeypatch):
    entries = [
        *llm_runner.MODEL_CATALOG["openai"],
        llm_runner.ModelCatalogEntry(
            "openai:gpt-future", "GPT Future", ("medium", "xhigh")
        ),
    ]
    monkeypatch.setitem(llm_runner.MODEL_CATALOG, "openai", entries)

    assert (
        llm_runner._responses_effort("openai:gpt-future", "openai", reasoning=True)
        == "medium"
    )


def test_responses_shim_strips_ref_siblings_from_the_output_schema():
    from pydantic import BaseModel, Field

    class Inner(BaseModel):
        a: str

    class Outer(BaseModel):
        inner: Inner = Field(description="the inner thing")

    model = llm_runner._compatible_openai_responses_class()(
        id="gpt-5.6-terra", api_key="k"
    )
    params = model.get_request_params(messages=[], response_format=Outer)

    node = params["text"]["format"]["schema"]["properties"]["inner"]
    assert "$ref" in node
    assert "description" not in node


def test_responses_shim_drops_an_empty_reasoning_object():
    model = llm_runner._compatible_openai_responses_class()(
        id="gpt-5.6-terra", api_key="k"
    )
    assert "reasoning" not in model.get_request_params(messages=[])


def test_responses_shim_keeps_a_populated_reasoning_object():
    model = llm_runner._compatible_openai_responses_class()(
        id="gpt-5.6-terra", api_key="k", reasoning={"effort": "xhigh"}
    )
    params = model.get_request_params(messages=[])
    assert params["reasoning"] == {"effort": "xhigh"}


def _truncated_response():
    """A Responses payload cut off at the request's output-token ceiling."""
    return SimpleNamespace(
        id="resp_094b58b7e15b7927",
        status="incomplete",
        incomplete_details=SimpleNamespace(reason="max_output_tokens"),
        error=None,
        output=[],
        output_text='{"summary": "half a sen',
        usage=SimpleNamespace(
            input_tokens=4200,
            input_tokens_details=SimpleNamespace(cached_tokens=0),
            output_tokens=32000,
            output_tokens_details=SimpleNamespace(reasoning_tokens=11000),
            total_tokens=36200,
        ),
    )


def test_responses_shim_records_a_response_cut_off_at_the_token_ceiling():
    # agno logs `status='incomplete'` and then discards it -- _parse_provider_response
    # receives the whole Response but carries neither the status nor
    # incomplete_details into ModelResponse -- so a truncated body reaches the
    # JSON parsers, fails all three, and arrives at expect_schema as a bare
    # `str`. Keep the fact on agno's own provider_data channel, which
    # _response.py copies onto RunOutput.model_provider_data.
    model = llm_runner._compatible_openai_responses_class()(
        id="gpt-5.6-terra", api_key="k", max_output_tokens=32000
    )

    parsed = model._parse_provider_response(cast(Response, _truncated_response()))

    assert parsed.provider_data is not None
    assert parsed.provider_data[llm_runner.INCOMPLETE_KEY] == {
        "reason": "max_output_tokens",
        "ceiling": 32000,
    }


def test_responses_shim_leaves_a_completed_response_alone():
    model = llm_runner._compatible_openai_responses_class()(
        id="gpt-5.6-terra", api_key="k"
    )
    complete = _truncated_response()
    complete.status = "completed"
    complete.incomplete_details = None

    parsed = model._parse_provider_response(cast(Response, complete))

    assert parsed.role == "assistant"
    assert llm_runner.INCOMPLETE_KEY not in (parsed.provider_data or {})


def _deepseek_response(*, reasoning_text: str | None):
    """A DeepSeek Responses payload.

    Live shape, verified against deepseek-v4-flash: a reasoning item carries its
    chain-of-thought in `content[].text` under `type == "reasoning_text"`, and
    its `summary` is ALWAYS `[]` -- DeepSeek documents `reasoning.summary` as
    "accepted but no summary is generated".
    """
    output = []
    if reasoning_text is not None:
        output.append(
            SimpleNamespace(
                type="reasoning",
                summary=[],
                content=[SimpleNamespace(type="reasoning_text", text=reasoning_text)],
            )
        )
    output.append(SimpleNamespace(type="message", content=[]))
    return SimpleNamespace(
        id="resp_ds_1",
        status="completed",
        incomplete_details=None,
        error=None,
        output=output,
        output_text="9.8 is larger.",
        usage=SimpleNamespace(
            input_tokens=23,
            input_tokens_details=SimpleNamespace(cached_tokens=0),
            output_tokens=171,
            output_tokens_details=SimpleNamespace(reasoning_tokens=159),
            total_tokens=194,
        ),
    )


def test_deepseek_recovers_real_reasoning_instead_of_echoing_the_answer():
    # agno looks for reasoning in a reasoning item's `summary`. DeepSeek never
    # populates it, so agno falls through to
    #     elif self.reasoning is not None:
    #         model_response.reasoning_content = response.output_text
    # copying the visible answer into the reasoning channel on EVERY
    # non-streaming call. reasoning_summary="auto" does not prevent it -- that
    # only guards the streaming branch.
    model = llm_runner._compatible_deepseek_responses_class()(
        id="deepseek-v4-flash", api_key="k", reasoning={"effort": "max"}
    )

    parsed = model._parse_provider_response(
        cast(Response, _deepseek_response(reasoning_text="9.8 = 9.80, so 9.8 wins."))
    )

    assert parsed.reasoning_content == "9.8 = 9.80, so 9.8 wins."
    assert parsed.content == "9.8 is larger."


def test_deepseek_drops_the_reasoning_echo_when_thinking_is_off():
    # effort="none" produces no reasoning item at all, so anything agno left in
    # the reasoning channel is the echo. The visible answer is never reasoning.
    model = llm_runner._compatible_deepseek_responses_class()(
        id="deepseek-v4-flash", api_key="k", reasoning={"effort": "none"}
    )

    parsed = model._parse_provider_response(
        cast(Response, _deepseek_response(reasoning_text=None))
    )

    assert parsed.reasoning_content is None
    assert parsed.content == "9.8 is larger."


def test_deepseek_maps_its_streamed_reasoning_deltas():
    # DeepSeek streams chain-of-thought as `response.reasoning_text.delta`
    # (measured: 177 deltas on one effort="max" turn). agno has a branch only for
    # `response.reasoning_summary_text.delta`, so every one of these was dropped
    # and a reasoning turn streamed no reasoning at all.
    model = llm_runner._compatible_deepseek_responses_class()(
        id="deepseek-v4-flash", api_key="k", reasoning={"effort": "max"}
    )
    event = SimpleNamespace(type="response.reasoning_text.delta", delta="We need")

    parsed, tool_use = model._parse_provider_response_delta(
        cast(ResponseStreamEvent, event), cast(Message, None), {"seen": 1}
    )

    assert parsed.reasoning_content == "We need"
    assert parsed.content is None
    assert tool_use == {"seen": 1}


def _run_output(content, *, truncated: bool):
    return SimpleNamespace(
        content=content,
        model="gpt-5.6-terra",
        model_provider="OpenAI",
        status="completed",
        metrics=SimpleNamespace(
            input_tokens=4200, output_tokens=32000, reasoning_tokens=11000
        ),
        model_provider_data=(
            {
                llm_runner.INCOMPLETE_KEY: {
                    "reason": "max_output_tokens",
                    "ceiling": 32000,
                }
            }
            if truncated
            else {"response_id": "resp_1"}
        ),
    )


class _Schema(BaseModel):
    summary: str


def test_unparsed_schema_failure_names_truncation_rather_than_just_got_str():
    # "Expected _Schema, got str" is true of a truncation, a refusal and a
    # rejected request alike. Only the ceiling tells you which lever to pull.
    with pytest.raises(llm_runner.UnparsedAgentOutput) as excinfo:
        llm_runner.expect_schema(
            _run_output('{"summary": "half a sen', truncated=True),
            _Schema,
            source="profile-extract",
        )

    message = str(excinfo.value)
    assert "cut off" in message
    assert "max_output_tokens" in message
    assert "ceiling=32000" in message


def test_untruncated_schema_failure_does_not_claim_truncation():
    with pytest.raises(llm_runner.UnparsedAgentOutput) as excinfo:
        llm_runner.expect_schema(
            _run_output("Sorry, I cannot help with that.", truncated=False),
            _Schema,
            source="profile-extract",
        )

    assert "cut off" not in str(excinfo.value)


def test_truncated_prose_is_rejected_rather_than_returned_as_a_whole_answer():
    # expect_text's only checks are "not an error status" and "not blank", and a
    # response cut off mid-sentence passes both -- so half an answer reached the
    # caller as a complete one. Nothing downstream can tell the difference.
    with pytest.raises(llm_runner.UnparsedAgentOutput) as excinfo:
        llm_runner.expect_text(
            _run_output("Here are the three things you should empha", truncated=True),
            source="coach-persona",
        )

    assert "cut off" in str(excinfo.value)


def test_complete_prose_is_still_returned():
    assert (
        llm_runner.expect_text(
            _run_output("A whole answer.", truncated=False), source="coach-persona"
        )
        == "A whole answer."
    )
