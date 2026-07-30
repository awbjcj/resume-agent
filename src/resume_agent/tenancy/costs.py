from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from resume_agent.tenancy.system_db import LlmRate

MILLION = 1_000_000


@dataclass(frozen=True)
class MeteredUsage:
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    audio_input_tokens: int = 0
    audio_output_tokens: int = 0
    total_tokens: int = 0
    tool_units: int = 0
    provider_cost_micros: int | None = None
    reasoning_effort: str | None = None
    reasoning_mode: str | None = None


@dataclass(frozen=True)
class CostLine:
    kind: str
    units: int
    rate_micros: int
    cost_micros: int


@dataclass(frozen=True)
class PricedUsage:
    total_micros: int | None
    tool_micros: int
    pricing_status: str
    rate_id: str | None
    lines: tuple[CostLine, ...] = field(default_factory=tuple)


def normalize_provider(value: str) -> str:
    folded = value.casefold().replace(" ", "")
    if "anthropic" in folded or "claude" in folded:
        return "anthropic"
    if "openai" in folded:
        return "openai"
    if "google" in folded or "gemini" in folded:
        return "gemini"
    if "deepseek" in folded:
        return "deepseek"
    return value.casefold()


def _cost(units: int, rate_micros: int) -> int:
    if units <= 0:
        return 0
    return (units * rate_micros + MILLION - 1) // MILLION


def find_rate(
    engine: Engine,
    provider: str,
    model: str,
    *,
    input_tokens: int = 0,
    now: datetime | None = None,
) -> LlmRate | None:
    moment = now or datetime.now(timezone.utc)
    with Session(engine) as session:
        return (
            session.execute(
                select(LlmRate)
                .where(
                    LlmRate.provider == normalize_provider(provider),
                    LlmRate.model == model,
                    LlmRate.context_min_tokens <= input_tokens,
                    or_(
                        LlmRate.context_max_tokens.is_(None),
                        LlmRate.context_max_tokens >= input_tokens,
                    ),
                    LlmRate.effective_from <= moment,
                    or_(LlmRate.effective_to.is_(None), LlmRate.effective_to > moment),
                )
                .order_by(
                    LlmRate.context_min_tokens.desc(), LlmRate.effective_from.desc()
                )
            )
            .scalars()
            .first()
        )


def has_active_rate(
    engine: Engine, provider: str, model: str, *, now: datetime | None = None
) -> bool:
    moment = now or datetime.now(timezone.utc)
    with Session(engine) as session:
        return (
            session.execute(
                select(LlmRate.id).where(
                    LlmRate.provider == normalize_provider(provider),
                    LlmRate.model == model,
                    LlmRate.effective_from <= moment,
                    or_(LlmRate.effective_to.is_(None), LlmRate.effective_to > moment),
                )
            ).first()
            is not None
        )


def calculate_cost(
    engine: Engine, usage: MeteredUsage, *, now: datetime | None = None
) -> PricedUsage:
    provider = normalize_provider(usage.provider)
    rate = find_rate(
        engine,
        provider,
        usage.model,
        input_tokens=usage.input_tokens,
        now=now,
    )
    if rate is None:
        return PricedUsage(None, 0, "RATE_UNAVAILABLE", None)

    ordinary_input = usage.input_tokens
    if provider != "anthropic":
        ordinary_input = max(
            0,
            usage.input_tokens - usage.cache_read_tokens - usage.cache_write_tokens,
        )
    components = (
        ("INPUT", ordinary_input, rate.input_micros_per_million),
        ("CACHE_READ", usage.cache_read_tokens, rate.cache_read_micros_per_million),
        ("CACHE_WRITE", usage.cache_write_tokens, rate.cache_write_micros_per_million),
        ("OUTPUT", usage.output_tokens, rate.output_micros_per_million),
        ("TOOL", usage.tool_units * MILLION, rate.tool_micros_per_unit),
    )
    lines: list[CostLine] = []
    for kind, units, component_rate in components:
        if units and component_rate is None:
            return PricedUsage(None, 0, "RATE_UNAVAILABLE", rate.id)
        resolved_rate = component_rate or 0
        cost = _cost(units, resolved_rate)
        if units:
            lines.append(CostLine(kind, units, resolved_rate, cost))
    tool_micros = sum(line.cost_micros for line in lines if line.kind == "TOOL")
    return PricedUsage(
        sum(line.cost_micros for line in lines),
        tool_micros,
        "PRICED",
        rate.id,
        tuple(lines),
    )


def _micros_per_million(dollars: float) -> int:
    return round(dollars * MILLION)


def seed_llm_rates(engine: Engine) -> None:
    start = datetime(2026, 7, 28, tzinfo=timezone.utc)
    sonnet_intro_end = datetime(2026, 9, 1, tzinfo=timezone.utc)
    openai = "https://developers.openai.com/api/docs/pricing"
    anthropic = "https://platform.claude.com/docs/en/about-claude/pricing"
    gemini = "https://ai.google.dev/gemini-api/docs/pricing"
    deepseek = "https://api-docs.deepseek.com/quick_start/pricing"
    rows = [
        ("anthropic", "claude-haiku-4-5", 1, 0.1, 1.25, 5, 10_000, anthropic, 0, None),
        ("anthropic", "claude-sonnet-5", 2, 0.2, 2.5, 10, 10_000, anthropic, 0, None),
        ("anthropic", "claude-opus-4-8", 5, 0.5, 6.25, 25, 10_000, anthropic, 0, None),
        ("anthropic", "claude-opus-5", 5, 0.5, 6.25, 25, 10_000, anthropic, 0, None),
        ("openai", "gpt-5.6-sol", 5, 0.5, 6.25, 30, 10_000, openai, 0, None),
        ("openai", "gpt-5.6-terra", 2.5, 0.25, 3.125, 15, 10_000, openai, 0, None),
        ("openai", "gpt-5.6-luna", 1, 0.1, 1.25, 6, 10_000, openai, 0, None),
        ("openai", "gpt-5.5", 5, 0.5, None, 30, 10_000, openai, 0, None),
        ("openai", "gpt-5.5-pro", 30, None, None, 180, 10_000, openai, 0, None),
        ("openai", "gpt-5.4-mini", 0.75, 0.075, None, 4.5, 10_000, openai, 0, None),
        (
            "gemini",
            "gemini-3.5-flash-lite",
            0.3,
            0.03,
            None,
            2.5,
            14_000,
            gemini,
            0,
            None,
        ),
        ("gemini", "gemini-3.6-flash", 1.5, 0.15, None, 7.5, 14_000, gemini, 0, None),
        ("gemini", "gemini-3.5-flash", 1.5, 0.15, None, 9, 14_000, gemini, 0, None),
        (
            "gemini",
            "gemini-3.1-pro-preview",
            2,
            0.2,
            None,
            12,
            14_000,
            gemini,
            0,
            200_000,
        ),
        (
            "gemini",
            "gemini-3.1-pro-preview",
            4,
            0.4,
            None,
            18,
            14_000,
            gemini,
            200_001,
            None,
        ),
        (
            "deepseek",
            "deepseek-v4-flash",
            0.14,
            0.0028,
            None,
            0.28,
            None,
            deepseek,
            0,
            None,
        ),
        (
            "deepseek",
            "deepseek-v4-pro",
            0.435,
            0.003625,
            None,
            0.87,
            None,
            deepseek,
            0,
            None,
        ),
    ]

    def stamp(value: datetime) -> datetime:
        return (
            value.astimezone(timezone.utc).replace(tzinfo=None)
            if value.tzinfo
            else value
        )

    with Session(engine) as session:
        existing = {
            (row.provider, row.model, row.context_min_tokens, stamp(row.effective_from))
            for row in session.execute(select(LlmRate)).scalars()
        }
        for (
            provider,
            model,
            input_rate,
            cache_read,
            cache_write,
            output_rate,
            tool,
            source,
            minimum,
            maximum,
        ) in rows:
            key = (provider, model, minimum, stamp(start))
            if key in existing:
                continue
            session.add(
                LlmRate(
                    id=uuid.uuid4().hex,
                    provider=provider,
                    model=model,
                    context_min_tokens=minimum,
                    context_max_tokens=maximum,
                    input_micros_per_million=_micros_per_million(input_rate),
                    cache_read_micros_per_million=(
                        _micros_per_million(cache_read)
                        if cache_read is not None
                        else None
                    ),
                    cache_write_micros_per_million=(
                        _micros_per_million(cache_write)
                        if cache_write is not None
                        else None
                    ),
                    output_micros_per_million=_micros_per_million(output_rate),
                    tool_micros_per_unit=tool,
                    effective_from=start,
                    effective_to=(
                        sonnet_intro_end
                        if provider == "anthropic" and model == "claude-sonnet-5"
                        else None
                    ),
                    source_url=source,
                )
            )
        sonnet_intro = (
            session.execute(
                select(LlmRate).where(
                    LlmRate.provider == "anthropic",
                    LlmRate.model == "claude-sonnet-5",
                    LlmRate.effective_from == start,
                )
            )
            .scalars()
            .first()
        )
        if sonnet_intro is not None:
            sonnet_intro.effective_to = sonnet_intro_end
        future_key = (
            "anthropic",
            "claude-sonnet-5",
            0,
            stamp(sonnet_intro_end),
        )
        if future_key not in existing:
            session.add(
                LlmRate(
                    id=uuid.uuid4().hex,
                    provider="anthropic",
                    model="claude-sonnet-5",
                    input_micros_per_million=_micros_per_million(3),
                    cache_read_micros_per_million=_micros_per_million(0.3),
                    cache_write_micros_per_million=_micros_per_million(3.75),
                    output_micros_per_million=_micros_per_million(15),
                    tool_micros_per_unit=10_000,
                    effective_from=sonnet_intro_end,
                    source_url=anthropic,
                )
            )
        session.commit()
