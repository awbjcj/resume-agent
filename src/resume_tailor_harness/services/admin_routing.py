"""Deployment-level subscription-routing configuration use case."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from resume_tailor_harness.config import RouteMode, Settings
from resume_tailor_harness.llm_routing import (
    ROUTE_MODE_FIELDS,
    SUB2API_KEY_FIELDS,
    EffectiveMode,
    RouteConfigError,
    effective_mode,
)
from resume_tailor_harness.services.env_config import write_env_updates

BODY_TO_SETTING = {
    "base_url": "sub2api_base_url",
    **{f"{provider}_key": field for provider, field in SUB2API_KEY_FIELDS.items()},
    **{field: field for field in ROUTE_MODE_FIELDS.values()},
}


@dataclass(frozen=True)
class RoutingKeyState:
    is_set: bool
    hint: str | None


@dataclass(frozen=True)
class ProviderRoutingState:
    provider: str
    route_mode: RouteMode
    effective_mode: EffectiveMode | None
    configuration_error: str | None
    key: RoutingKeyState


@dataclass(frozen=True)
class RoutingState:
    base_url: str
    providers: tuple[ProviderRoutingState, ...]


def routing_state(settings: Settings) -> RoutingState:
    providers: list[ProviderRoutingState] = []
    for provider, key_field in SUB2API_KEY_FIELDS.items():
        error = None
        resolved = None
        try:
            resolved = effective_mode(provider, settings)
        except RouteConfigError as exc:
            error = str(exc)
        value = str(getattr(settings, key_field) or "")
        providers.append(
            ProviderRoutingState(
                provider=provider,
                route_mode=getattr(settings, ROUTE_MODE_FIELDS[provider]),
                effective_mode=resolved,
                configuration_error=error,
                key=RoutingKeyState(
                    is_set=bool(value),
                    hint=value[-4:] if len(value) >= 8 else None,
                ),
            )
        )
    return RoutingState(settings.sub2api_base_url, tuple(providers))


def update_routing_settings(
    current: Settings,
    provided: Mapping[str, object],
    env_path: Path,
) -> Settings:
    candidate = current.model_copy(
        update={
            BODY_TO_SETTING[field]: value or "" for field, value in provided.items()
        }
    )
    errors: list[str] = []
    for provider in SUB2API_KEY_FIELDS:
        try:
            effective_mode(provider, candidate)
        except RouteConfigError as exc:
            errors.append(str(exc))
    if errors:
        raise RouteConfigError("; ".join(errors))
    updates = {
        BODY_TO_SETTING[field].upper(): str(value or "")
        for field, value in provided.items()
    }
    return write_env_updates(updates, env_path)
