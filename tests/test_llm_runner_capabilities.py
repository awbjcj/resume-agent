from resume_tailor_harness.llm_runner import ProviderCapabilities, provider_capabilities


def test_known_model_capabilities_are_model_gated():
    assert provider_capabilities("claude-sonnet-5") == ProviderCapabilities(
        supports_reasoning=True,
        supports_native_citations=True,
        supports_prompt_cache=True,
    )
    assert provider_capabilities("claude-haiku-4-5-20251001") == ProviderCapabilities(
        supports_reasoning=False,
        supports_native_citations=True,
        supports_prompt_cache=True,
    )
    assert provider_capabilities("openai:gpt-5.6").supports_reasoning is True
    assert provider_capabilities("openai:gpt-4o").supports_reasoning is False
    assert provider_capabilities("gemini:gemini-3.5-flash").supports_reasoning is True
    # Citations stay False even though DeepSeek now has native web search: it
    # runs the search server-side but returns no `url_citation` annotations.
    assert provider_capabilities("deepseek:deepseek-v4-pro") == ProviderCapabilities(
        supports_reasoning=True,
        supports_native_citations=False,
        supports_prompt_cache=True,
    )
    assert provider_capabilities("deepseek:deepseek-v3").supports_reasoning is False


def test_unknown_or_empty_model_is_conservative():
    disabled = ProviderCapabilities(False, False, False)
    assert provider_capabilities("") == disabled
    assert provider_capabilities("acme:workday") == disabled
    assert provider_capabilities("not-a-real-claude-model") == disabled
