from types import SimpleNamespace

import resume_agent.llm_runner as llm_runner
from resume_agent.llm_runner import build_model


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
