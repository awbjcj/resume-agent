"""Data-only registry for provider configuration and supported call surfaces."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class ProviderSpec:
    id: str
    label: str
    api_key_field: str
    subscription_key_field: str
    route_mode_field: str
    direct_base_url_field: str | None = None
    default_direct_base_url: str | None = None
    supports_transcription: bool = False
    supports_speech: bool = False


PROVIDER_SPECS = (
    ProviderSpec(
        id="anthropic",
        label="Anthropic",
        api_key_field="anthropic_api_key",
        subscription_key_field="sub2api_anthropic_key",
        route_mode_field="anthropic_route_mode",
        direct_base_url_field="anthropic_base_url",
        default_direct_base_url="https://api.anthropic.com",
    ),
    ProviderSpec(
        id="openai",
        label="OpenAI",
        api_key_field="openai_api_key",
        subscription_key_field="sub2api_openai_key",
        route_mode_field="openai_route_mode",
        direct_base_url_field="openai_base_url",
        default_direct_base_url="https://api.openai.com/v1",
        supports_transcription=True,
        supports_speech=True,
    ),
    ProviderSpec(
        id="gemini",
        label="Gemini",
        api_key_field="gemini_api_key",
        subscription_key_field="sub2api_gemini_key",
        route_mode_field="gemini_route_mode",
        supports_transcription=True,
    ),
    ProviderSpec(
        id="deepseek",
        label="DeepSeek",
        api_key_field="deepseek_api_key",
        subscription_key_field="sub2api_deepseek_key",
        route_mode_field="deepseek_route_mode",
    ),
)

PROVIDERS = tuple(spec.id for spec in PROVIDER_SPECS)
PROVIDER_LABELS = {spec.id: spec.label for spec in PROVIDER_SPECS}
PROVIDER_BY_ID = {spec.id: spec for spec in PROVIDER_SPECS}


def provider_spec(provider: str) -> ProviderSpec | None:
    return PROVIDER_BY_ID.get(provider)
