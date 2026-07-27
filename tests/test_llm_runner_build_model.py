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

    openai = build_model("openai:gpt-5.6", api_key="k", reasoning=True)
    assert openai.reasoning_effort == "high"

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
        cheap_response_verbosity=None,
        mid_model="claude-sonnet-5",
        mid_reasoning_effort="low",
        mid_response_verbosity=None,
        premium_model="openai:gpt-5.5",
        premium_reasoning_effort="xhigh",
        premium_response_verbosity="low",
    )
    monkeypatch.setattr(llm_runner, "get_settings", lambda: settings)

    claude = build_model("claude-sonnet-5", api_key="k", reasoning=True)
    openai = build_model("openai:gpt-5.5", api_key="k", reasoning=True)
    gemini = build_model("gemini:gemini-3.5-flash", api_key="k", reasoning=True)

    assert claude.output_config == {"effort": "low"}
    assert openai.reasoning_effort == "xhigh"
    assert openai.verbosity == "low"
    assert gemini.thinking_level == "minimal"
