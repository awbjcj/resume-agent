"""Admin-only, write-only subscription-routing configuration."""

from __future__ import annotations

from resume_tailor_harness.api.schemas.base import CamelModel
from resume_tailor_harness.config import RouteMode
from resume_tailor_harness.llm_routing import EffectiveMode


class RoutingKeyStatus(CamelModel):
    is_set: bool
    hint: str | None = None


class ProviderRoutingStatus(CamelModel):
    provider: str
    label: str
    route_mode: RouteMode
    effective_mode: EffectiveMode | None = None
    configuration_error: str | None = None
    key: RoutingKeyStatus


class RoutingConfigDoc(CamelModel):
    base_url: str
    providers: list[ProviderRoutingStatus]


class RoutingUpdate(CamelModel):
    """Only fields present in the request are written; null clears a key or URL."""

    base_url: str | None = None
    anthropic_key: str | None = None
    openai_key: str | None = None
    gemini_key: str | None = None
    deepseek_key: str | None = None
    anthropic_route_mode: RouteMode | None = None
    openai_route_mode: RouteMode | None = None
    gemini_route_mode: RouteMode | None = None
    deepseek_route_mode: RouteMode | None = None
