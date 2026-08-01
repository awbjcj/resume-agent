from types import SimpleNamespace

import resume_agent.llm_runner as llm_runner
from resume_agent.llm_runner import (
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

    deepseek = build_model("deepseek:deepseek-reasoner", api_key="k", reasoning=True)
    assert deepseek.use_thinking is True
    assert deepseek.reasoning_effort == "max"


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


def test_non_reasoning_deepseek_disables_thinking_rather_than_omitting_it():
    # Third instance of the "unset means provider decides" trap, after Gemini and
    # Anthropic. agno 2.8.2 reads use_thinking=None as the provider default, and
    # that default is ON for every deepseek-v4-* id -- so leaving it unset bought
    # thinking on every non-reasoning agent. Measured on the live coach turn: 7,779
    # characters of reasoning, streamed as 1,846 one-word deltas.
    #
    # Unlike Gemini 3 (which 400s on thinking_budget), an explicit disabled flag is
    # verified accepted on deepseek-chat, -v4-flash and -v4-pro alike, so one
    # uniform rule is safe -- no generation gate needed.
    for model_id in ("deepseek:deepseek-v4-pro", "deepseek:deepseek-v4-flash", "deepseek:deepseek-chat"):
        model = build_model(model_id, api_key="k")
        assert model.use_thinking is False, model_id
        assert model.get_request_params()["extra_body"]["thinking"] == {"type": "disabled"}


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

    assert params["reasoning"] == {"effort": "high"}
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
    assert build_model(
        "openai:gpt-5.6-terra", api_key="k"
    ).max_output_tokens == 16000
    assert (
        build_model("openai:gpt-5.6-terra", api_key="k", reasoning=True)
        .max_output_tokens
        == 32000
    )


def test_openai_effort_floor_is_the_lowest_effort_the_model_declares():
    assert (
        llm_runner._openai_effort("openai:gpt-5.6-terra", reasoning=False)
        == "none"
    )
    assert (
        llm_runner._openai_effort("openai:gpt-5.4-mini", reasoning=False)
        == "none"
    )
    assert (
        llm_runner._openai_effort("openai:gpt-5.5-pro", reasoning=False)
        == "medium"
    )


def test_openai_effort_is_unset_for_an_uncatalogued_model():
    model_id = "openai:gpt-5.9-experimental"
    assert llm_runner._openai_effort(model_id, reasoning=False) is None
    assert llm_runner._openai_effort(model_id, reasoning=True) is None


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
        llm_runner._openai_effort("openai:gpt-5.6-terra", reasoning=True)
        == "high"
    )
    assert (
        llm_runner._openai_effort("openai:gpt-5.5-pro", reasoning=True) == "high"
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
        llm_runner._openai_effort("openai:gpt-5.6-terra", reasoning=True) == "max"
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
        llm_runner._openai_effort("openai:gpt-future", reasoning=True)
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
