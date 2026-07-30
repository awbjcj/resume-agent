from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from types import SimpleNamespace

from sqlalchemy.orm import Session

from resume_agent.tenancy.context import current_context
from resume_agent.tenancy.costs import MeteredUsage, calculate_cost, normalize_provider
from resume_agent.tenancy.quotas import charge_shared_cost
from resume_agent.tenancy.system_db import UsageEvent, UsageLineItem

logger = logging.getLogger(__name__)

# Deprecated analytics weights. They remain populated for one compatibility
# release, but are never consulted by cost-quota enforcement.
WEIGHT_INPUT = 1.0
WEIGHT_OUTPUT = 3.0
WEIGHT_CACHE_READ = 0.1
WEIGHT_CACHE_CREATION = 1.25


def _value(obj: object, name: str, default: object = None) -> object:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _metric(metrics: object, name: str) -> int:
    value = _value(metrics, name, 0) or 0
    if isinstance(value, (list, tuple)):
        value = sum(item or 0 for item in value)
    if not isinstance(value, (int, float, str)):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _provider_cost_micros(metrics: object) -> int | None:
    value = _value(metrics, "cost")
    if not isinstance(value, (int, float, str)):
        return None
    try:
        return round(float(value) * 1_000_000)
    except (TypeError, ValueError):
        return None


def _fallback_identity(agent: object, response: object) -> tuple[str, str]:
    model = getattr(agent, "model", None)
    model_id = (
        getattr(response, "model", None)
        or getattr(model, "id", None)
        or getattr(agent, "model_id", None)
        or ""
    )
    provider = getattr(response, "model_provider", None)
    if not provider and model is not None:
        get_provider = getattr(model, "get_provider", None)
        if callable(get_provider):
            provider = get_provider()
        provider = provider or getattr(model, "provider", None)
    if not provider and model_id:
        from resume_agent.llm_runner import split_provider

        provider, model_id = split_provider(str(model_id))
    return normalize_provider(str(provider or "")), str(model_id)


def _detail_entries(metrics: object) -> Iterable[tuple[str, str, str, object]]:
    details = _value(metrics, "details")
    if not isinstance(details, Mapping):
        return ()
    entries: list[tuple[str, str, str, object]] = []
    for model_type, model_metrics in details.items():
        if isinstance(model_metrics, (list, tuple)):
            for detail in model_metrics:
                entries.append(
                    (
                        normalize_provider(str(_value(detail, "provider") or "")),
                        str(_value(detail, "id") or ""),
                        str(model_type).upper(),
                        detail,
                    )
                )
        elif isinstance(model_metrics, Mapping):
            # Compatibility with older Agno dict serializations.
            for model, detail in model_metrics.items():
                entries.append(
                    (
                        normalize_provider(
                            str(_value(detail, "provider") or model_type)
                        ),
                        str(_value(detail, "id") or model),
                        str(model_type).upper(),
                        detail,
                    )
                )
    return entries


def _nested_units(value: object) -> int:
    names = {
        "tool_units",
        "web_search_count",
        "web_search_requests",
        "web_search_queries",
        "search_queries",
    }
    if not isinstance(value, Mapping):
        return 0
    total = 0
    for key, item in value.items():
        if str(key).casefold() in names:
            try:
                total += int(item or 0)
            except (TypeError, ValueError):
                pass
        elif isinstance(item, Mapping):
            total += _nested_units(item)
    return total


def _metered(
    provider: str, model: str, metrics: object, *, model_type: str | None = None
) -> MeteredUsage:
    input_tokens = _metric(metrics, "input_tokens")
    output_tokens = _metric(metrics, "output_tokens")
    cache_write = _metric(metrics, "cache_write_tokens") or _metric(
        metrics, "cache_creation_tokens"
    )
    total = _metric(metrics, "total_tokens")
    audio_input = _metric(metrics, "audio_input_tokens")
    audio_output = _metric(metrics, "audio_output_tokens")
    return MeteredUsage(
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=_metric(metrics, "cache_read_tokens"),
        cache_write_tokens=cache_write,
        reasoning_tokens=_metric(metrics, "reasoning_tokens"),
        audio_input_tokens=audio_input,
        audio_output_tokens=audio_output,
        total_tokens=total or input_tokens + output_tokens,
        tool_units=(
            _metric(metrics, "tool_units")
            or _metric(metrics, "web_search_requests")
            or _metric(metrics, "search_queries")
            or _nested_units(_value(metrics, "provider_metrics"))
        ),
        provider_cost_micros=_provider_cost_micros(metrics),
        reasoning_effort=str(_value(metrics, "reasoning_effort") or "") or None,
        reasoning_mode=(
            str(_value(metrics, "reasoning_mode") or "") or model_type or None
        ),
    )


def record_call(agent: object, response: object) -> None:
    """Persist every exact Agno per-model metric entry and charge shared cost.

    Agno's aggregate metrics are used only when ``details`` is absent. This
    prevents double-counting and avoids guessing provider identity from a bare
    model id. Recording remains best-effort so telemetry cannot hide a useful
    provider response; preflight handles unknown rates before shared calls.
    """

    context = current_context()
    if context is None or context.system_engine is None:
        return
    try:
        metrics = getattr(response, "metrics", None)
        fallback_provider, fallback_model = _fallback_identity(agent, response)
        entries = list(_detail_entries(metrics))
        if not entries:
            entries = [(fallback_provider, fallback_model, "MODEL", metrics)]
        for provider, model, model_type, detail in entries:
            usage = _metered(
                provider or fallback_provider,
                model or fallback_model,
                detail,
                model_type=model_type,
            )
            from resume_agent.tenancy.limits import selected_key_is_own

            own_key = selected_key_is_own(usage.provider, agent)
            priced = calculate_cost(context.system_engine, usage)
            event = UsageEvent(
                user_id=context.user_id,
                provider=usage.provider or None,
                model=usage.model or None,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cache_read_tokens=usage.cache_read_tokens,
                cache_creation_tokens=usage.cache_write_tokens,
                cache_write_tokens=usage.cache_write_tokens,
                reasoning_tokens=usage.reasoning_tokens,
                audio_input_tokens=usage.audio_input_tokens,
                audio_output_tokens=usage.audio_output_tokens,
                total_tokens=usage.total_tokens,
                weighted_total=(
                    usage.input_tokens * WEIGHT_INPUT
                    + usage.output_tokens * WEIGHT_OUTPUT
                    + usage.cache_read_tokens * WEIGHT_CACHE_READ
                    + usage.cache_write_tokens * WEIGHT_CACHE_CREATION
                ),
                own_key=own_key,
                cost_micros=priced.total_micros,
                quota_cost_micros=0 if own_key else priced.total_micros or 0,
                tool_cost_micros=priced.tool_micros,
                provider_cost_micros=usage.provider_cost_micros,
                rate_id=priced.rate_id,
                pricing_status=priced.pricing_status,
                reasoning_effort=usage.reasoning_effort,
                reasoning_mode=usage.reasoning_mode,
            )
            with Session(context.system_engine) as session:
                session.add(event)
                session.flush()
                if priced.rate_id:
                    session.add_all(
                        UsageLineItem(
                            usage_event_id=event.id,
                            kind=line.kind,
                            units=line.units,
                            rate_micros=line.rate_micros,
                            cost_micros=line.cost_micros,
                            rate_id=priced.rate_id,
                        )
                        for line in priced.lines
                    )
                session.commit()
                event_id = event.id
            if not own_key and not context.is_admin and priced.total_micros is not None:
                charge_shared_cost(
                    context.system_engine,
                    context.user_id,
                    priced.total_micros,
                    usage_event_id=event_id,
                )
    except Exception:
        logger.warning("usage recording failed", exc_info=True)


def record_direct_usage(usage: MeteredUsage) -> None:
    """Send non-Agno provider calls through the same immutable recorder."""

    metrics = SimpleNamespace(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        reasoning_tokens=usage.reasoning_tokens,
        audio_input_tokens=usage.audio_input_tokens,
        audio_output_tokens=usage.audio_output_tokens,
        total_tokens=usage.total_tokens,
        tool_units=usage.tool_units,
        cost=(
            usage.provider_cost_micros / 1_000_000
            if usage.provider_cost_micros is not None
            else None
        ),
        reasoning_effort=usage.reasoning_effort,
        reasoning_mode=usage.reasoning_mode,
    )
    record_call(
        SimpleNamespace(model=SimpleNamespace(id=usage.model, provider=usage.provider)),
        SimpleNamespace(
            model=usage.model,
            model_provider=usage.provider,
            metrics=metrics,
        ),
    )
