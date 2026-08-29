from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from weakref import WeakKeyDictionary

from sqlalchemy import or_, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from resume_agent.tenancy.system_db import LlmRate

MILLION = 1_000_000

RATE_PERIOD_PEAK = "peak"
RATE_PERIOD_OFF_PEAK = "off_peak"
# DeepSeek's published peak windows, half-open [start, end) in UTC hours.
_PEAK_HOUR_BANDS = ((1, 4), (6, 10))
# From 2026-08-29 00:00 Beijing time, DeepSeek charges its off-peak rate for
# the entire Saturday/Sunday Beijing-time weekend. Keep the cutoff so that
# historical usage before the provider change retains the earlier daily bands.
_DEEPSEEK_WEEKEND_OFF_PEAK_FROM = datetime(2026, 8, 28, 16, tzinfo=timezone.utc)
_BEIJING_TIMEZONE = timezone(timedelta(hours=8))


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


def _rate_period(moment: datetime) -> str:
    """The time-of-day band ``moment`` falls in, for period-restricted rates."""
    beijing_time = moment.astimezone(_BEIJING_TIMEZONE)
    if (
        moment >= _DEEPSEEK_WEEKEND_OFF_PEAK_FROM
        and beijing_time.weekday() >= 5
    ):
        return RATE_PERIOD_OFF_PEAK
    hour = moment.astimezone(timezone.utc).hour
    if any(start <= hour < end for start, end in _PEAK_HOUR_BANDS):
        return RATE_PERIOD_PEAK
    return RATE_PERIOD_OFF_PEAK


def _cost(units: int, rate_micros: int) -> int:
    if units <= 0:
        return 0
    return (units * rate_micros + MILLION - 1) // MILLION


def _active_rates(
    engine: Engine, provider: str, model: str, moment: datetime
) -> list[LlmRate]:
    with Session(engine) as session:
        rows = list(
            session.execute(
                select(LlmRate)
                .where(
                    LlmRate.provider == normalize_provider(provider),
                    LlmRate.model == model,
                    LlmRate.effective_from <= moment,
                    or_(LlmRate.effective_to.is_(None), LlmRate.effective_to > moment),
                )
                .order_by(
                    LlmRate.context_min_tokens.desc(), LlmRate.effective_from.desc()
                )
            ).scalars()
        )
        # Detach with every column loaded so the cached rows outlive the
        # session without a lazy load.
        session.expunge_all()
    return rows


def find_rate(
    engine: Engine,
    provider: str,
    model: str,
    *,
    input_tokens: int = 0,
    now: datetime | None = None,
) -> LlmRate | None:
    """Resolve the rate row for a call, caching the model's active rate set.

    Context-band selection happens in Python over the cached set rather than in
    SQL, so a run that prices thousands of calls at different input sizes still
    issues one query per model per TTL instead of one per call.
    """
    cacheable = now is None
    key = (normalize_provider(provider), model)
    rows: list[LlmRate] | None = None
    if cacheable:
        entry = _rate_rows_cache.setdefault(engine, {}).get(key)
        if entry is not None and time.monotonic() - entry[0] < RATE_CACHE_TTL_SECONDS:
            rows = entry[1]
    moment = now or datetime.now(timezone.utc)
    if rows is None:
        rows = _active_rates(engine, provider, model, moment)
        if cacheable:
            _rate_rows_cache.setdefault(engine, {})[key] = (time.monotonic(), rows)
    # The row set is cached (it only depends on the date window), but which
    # period is live depends on the current hour, so that check always reads
    # the fresh ``moment`` rather than anything cached.
    current_period = _rate_period(moment)
    for rate in rows:
        if rate.rate_period is not None and rate.rate_period != current_period:
            continue
        if rate.context_min_tokens <= input_tokens and (
            rate.context_max_tokens is None or rate.context_max_tokens >= input_tokens
        ):
            return rate
    return None


# Rate rows are near-static reference data edited only by an admin, but
# has_active_rate sits on the hot path in front of every shared-key call and
# opened its own session each time. The cache is keyed by engine so entries die
# with the database they describe, which is also what keeps tests isolated.
RATE_CACHE_TTL_SECONDS = 60.0
_rate_cache: WeakKeyDictionary[Engine, dict[tuple[str, str], tuple[float, bool]]] = (
    WeakKeyDictionary()
)


_rate_rows_cache: WeakKeyDictionary[
    Engine, dict[tuple[str, str], tuple[float, list[LlmRate]]]
] = WeakKeyDictionary()


def invalidate_rate_cache(engine: Engine | None = None) -> None:
    """Drop cached rate lookups after an admin edits or seeds rates."""
    if engine is None:
        _rate_cache.clear()
        _rate_rows_cache.clear()
    else:
        _rate_cache.pop(engine, None)
        _rate_rows_cache.pop(engine, None)


def has_active_rate(
    engine: Engine, provider: str, model: str, *, now: datetime | None = None
) -> bool:
    # An explicit ``now`` is a test or a backfill asking about a different
    # moment; only the real-clock path is cacheable.
    cacheable = now is None
    key = (normalize_provider(provider), model)
    if cacheable:
        entry = _rate_cache.setdefault(engine, {}).get(key)
        if entry is not None and time.monotonic() - entry[0] < RATE_CACHE_TTL_SECONDS:
            return entry[1]
    moment = now or datetime.now(timezone.utc)
    with Session(engine) as session:
        found = (
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
    if cacheable:
        _rate_cache.setdefault(engine, {})[key] = (time.monotonic(), found)
    return found


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
    # Keep the original seed rates for historical usage.  OpenAI's published
    # standard prices changed after this seed was introduced, so active usage
    # must resolve to a separately versioned rate rather than retroactively
    # repricing events from July.
    openai_price_update = datetime(2026, 8, 1, tzinfo=timezone.utc)
    # GPT-5.6 Sol's current published Standard rate was rechecked on
    # 2026-08-27. Keep the former Sol rate for historical usage, then make the
    # new rate effective from this catalog refresh rather than rewriting it.
    openai_sol_price_update = datetime(2026, 8, 27, tzinfo=timezone.utc)
    gemini_price_update = datetime(2026, 8, 15, tzinfo=timezone.utc)
    # Google publishes both Flash models' current rate as promotional "through
    # 2026-12-31", doubling on 2027-01-01. Seeding only the promo left the
    # quota system under-billing shared-key spend 2x from January, on a date
    # nobody would be watching -- so the reversion is scheduled now.
    gemini_promo_end = datetime(2027, 1, 1, tzinfo=timezone.utc)
    # Sonnet 5 launched with a September 1 price increase scheduled. Anthropic
    # later made the $2/$10 launch price permanent. Retain the old boundary
    # only to repair databases that already contain the cancelled future row.
    sonnet_cancelled_increase = datetime(2026, 9, 1, tzinfo=timezone.utc)
    deepseek_price_update = datetime(2026, 8, 16, 16, 0, tzinfo=timezone.utc)
    openai = "https://developers.openai.com/api/docs/pricing"
    openai_sol = "https://developers.openai.com/api/docs/models/gpt-5.6-sol"
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
        # Embeddings have input-token pricing only.  The direct embedding
        # client records input tokens through the same shared/personal spend
        # seam as agent calls, so the zero output rate is intentional.
        ("openai", "text-embedding-3-small", 0.02, None, None, 0, 0, openai, 0, None),
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
        # Selectable in MODEL_CATALOG, so it needs a rate for shared-key budget
        # enforcement. Seeded straight at the promotional rate -- unlike 3.6
        # Flash there is no earlier usage at a different price to preserve.
        (
            "gemini",
            "gemini-3.7-flash",
            0.75,
            0.075,
            None,
            3.75,
            14_000,
            gemini,
            0,
            None,
        ),
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
                    effective_to=None,
                    source_url=source,
                )
            )
        for model in ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"):
            legacy_rate = (
                session.execute(
                    select(LlmRate).where(
                        LlmRate.provider == "openai",
                        LlmRate.model == model,
                        LlmRate.effective_from == start,
                    )
                )
                .scalars()
                .first()
            )
            if legacy_rate is not None:
                legacy_rate.effective_to = openai_price_update

        # Standard (not Batch) OpenAI pricing, verified against the official pricing page
        # on 2026-08-01.  Cache writes use OpenAI's published 1.25x input
        # multiplier for GPT-5.6.
        for model, input_rate, cache_read, cache_write, output_rate in (
            ("gpt-5.6-sol", 5, 0.5, 6.25, 30),
            ("gpt-5.6-terra", 2, 0.2, 2.5, 12),
            ("gpt-5.6-luna", 0.2, 0.02, 0.25, 1.2),
        ):
            key = ("openai", model, 0, stamp(openai_price_update))
            current_rate = None
            if key in existing:
                current_rate = (
                    session.execute(
                        select(LlmRate).where(
                            LlmRate.provider == "openai",
                            LlmRate.model == model,
                            LlmRate.context_min_tokens == 0,
                            LlmRate.effective_from == openai_price_update,
                        )
                    )
                    .scalars()
                    .first()
                )
            if current_rate is None:
                current_rate = LlmRate(
                    id=uuid.uuid4().hex,
                    provider="openai",
                    model=model,
                    effective_from=openai_price_update,
                )
                session.add(current_rate)
            current_rate.input_micros_per_million = _micros_per_million(input_rate)
            current_rate.cache_read_micros_per_million = _micros_per_million(cache_read)
            current_rate.cache_write_micros_per_million = _micros_per_million(
                cache_write
            )
            current_rate.output_micros_per_million = _micros_per_million(output_rate)
            current_rate.tool_micros_per_unit = 10_000
            current_rate.source_url = openai

        # OpenAI reduced GPT-5.6 Sol's Standard price to $4/M uncached input,
        # $0.40/M cached input, and $20/M output. Cache writes remain 1.25x
        # the uncached input rate, or $5/M. Leave Terra and Luna untouched:
        # their current prices are already represented by the 2026-08-01 rows.
        previous_sol_rate = (
            session.execute(
                select(LlmRate).where(
                    LlmRate.provider == "openai",
                    LlmRate.model == "gpt-5.6-sol",
                    LlmRate.context_min_tokens == 0,
                    LlmRate.effective_from == openai_price_update,
                )
            )
            .scalars()
            .first()
        )
        if previous_sol_rate is not None:
            previous_sol_rate.effective_to = openai_sol_price_update
        sol_key = ("openai", "gpt-5.6-sol", 0, stamp(openai_sol_price_update))
        current_sol_rate = None
        if sol_key in existing:
            current_sol_rate = (
                session.execute(
                    select(LlmRate).where(
                        LlmRate.provider == "openai",
                        LlmRate.model == "gpt-5.6-sol",
                        LlmRate.context_min_tokens == 0,
                        LlmRate.effective_from == openai_sol_price_update,
                    )
                )
                .scalars()
                .first()
            )
        if current_sol_rate is None:
            current_sol_rate = LlmRate(
                id=uuid.uuid4().hex,
                provider="openai",
                model="gpt-5.6-sol",
                effective_from=openai_sol_price_update,
            )
            session.add(current_sol_rate)
        current_sol_rate.input_micros_per_million = _micros_per_million(4)
        current_sol_rate.cache_read_micros_per_million = _micros_per_million(0.4)
        current_sol_rate.cache_write_micros_per_million = _micros_per_million(5)
        current_sol_rate.output_micros_per_million = _micros_per_million(20)
        current_sol_rate.tool_micros_per_unit = 10_000
        current_sol_rate.source_url = openai_sol

        # Google changed Gemini 3.6 Flash's standard pricing on 2026-08-15.
        # Keep the former rate for historical usage, then add the current row
        # rather than silently repricing the usage events recorded before the
        # correction. Gemini 3.1 Flash Lite is selectable in MODEL_CATALOG and
        # needs a rate for shared-key budget enforcement as well.
        legacy_flash = (
            session.execute(
                select(LlmRate).where(
                    LlmRate.provider == "gemini",
                    LlmRate.model == "gemini-3.6-flash",
                    LlmRate.effective_from == start,
                )
            )
            .scalars()
            .first()
        )
        if legacy_flash is not None:
            legacy_flash.effective_to = gemini_price_update
        for model, input_rate, cache_read, output_rate in (
            ("gemini-3.6-flash", 0.75, 0.075, 3.75),
            ("gemini-3.1-flash-lite", 0.25, 0.025, 1.5),
        ):
            key = ("gemini", model, 0, stamp(gemini_price_update))
            current_rate = None
            if key in existing:
                current_rate = (
                    session.execute(
                        select(LlmRate).where(
                            LlmRate.provider == "gemini",
                            LlmRate.model == model,
                            LlmRate.context_min_tokens == 0,
                            LlmRate.effective_from == gemini_price_update,
                        )
                    )
                    .scalars()
                    .first()
                )
            if current_rate is None:
                current_rate = LlmRate(
                    id=uuid.uuid4().hex,
                    provider="gemini",
                    model=model,
                    effective_from=gemini_price_update,
                )
                session.add(current_rate)
            current_rate.input_micros_per_million = _micros_per_million(input_rate)
            current_rate.cache_read_micros_per_million = _micros_per_million(
                cache_read
            )
            current_rate.cache_write_micros_per_million = None
            current_rate.output_micros_per_million = _micros_per_million(output_rate)
            # Google Search is $14 / 1,000 paid grounded prompts. The provider's
            # monthly included allowance is account-level state we cannot infer
            # from one request, so shared-key metering records the billed unit.
            current_rate.tool_micros_per_unit = 14_000
            current_rate.source_url = gemini

        # Close both Flash promos on 2027-01-01 and schedule the doubled rate
        # from that moment. `find_rate` filters `effective_from <= moment <
        # effective_to`, so the future row is inert until the promo lapses and
        # authoritative the instant it does -- no dated migration to remember.
        # 3.1 Flash-Lite is deliberately excluded: its $0.25 is the plain listed
        # rate, not a promotional one.
        for model, promo_from, input_rate, cache_read, output_rate in (
            ("gemini-3.6-flash", gemini_price_update, 1.5, 0.15, 7.5),
            ("gemini-3.7-flash", start, 1.5, 0.15, 7.5),
        ):
            promo_rate = (
                session.execute(
                    select(LlmRate).where(
                        LlmRate.provider == "gemini",
                        LlmRate.model == model,
                        LlmRate.context_min_tokens == 0,
                        LlmRate.effective_from == promo_from,
                    )
                )
                .scalars()
                .first()
            )
            if promo_rate is not None:
                promo_rate.effective_to = gemini_promo_end
            future_key = ("gemini", model, 0, stamp(gemini_promo_end))
            if future_key not in existing:
                session.add(
                    LlmRate(
                        id=uuid.uuid4().hex,
                        provider="gemini",
                        model=model,
                        input_micros_per_million=_micros_per_million(input_rate),
                        cache_read_micros_per_million=_micros_per_million(cache_read),
                        cache_write_micros_per_million=None,
                        output_micros_per_million=_micros_per_million(output_rate),
                        tool_micros_per_unit=14_000,
                        effective_from=gemini_promo_end,
                        source_url=gemini,
                    )
                )

        # DeepSeek moves both models from a flat rate to peak/off-peak hourly
        # billing at deepseek_price_update (see _rate_period for the UTC hour
        # bands). Close the flat seed row at the cutover and seed the two
        # period rows per model from that moment on, verified against the
        # official pricing page on 2026-08-14.
        for model in ("deepseek-v4-flash", "deepseek-v4-pro"):
            flat_rate = (
                session.execute(
                    select(LlmRate).where(
                        LlmRate.provider == "deepseek",
                        LlmRate.model == model,
                        LlmRate.effective_from == start,
                    )
                )
                .scalars()
                .first()
            )
            if flat_rate is not None:
                flat_rate.effective_to = deepseek_price_update
        for model, period, input_rate, cache_read, output_rate in (
            ("deepseek-v4-flash", RATE_PERIOD_OFF_PEAK, 0.22, 0.007, 0.66),
            ("deepseek-v4-flash", RATE_PERIOD_PEAK, 0.44, 0.014, 1.32),
            ("deepseek-v4-pro", RATE_PERIOD_OFF_PEAK, 0.66, 0.022, 1.98),
            ("deepseek-v4-pro", RATE_PERIOD_PEAK, 1.32, 0.044, 3.96),
        ):
            key = ("deepseek", model, 0, stamp(deepseek_price_update))
            current_rate = None
            if key in existing:
                current_rate = (
                    session.execute(
                        select(LlmRate).where(
                            LlmRate.provider == "deepseek",
                            LlmRate.model == model,
                            LlmRate.context_min_tokens == 0,
                            LlmRate.effective_from == deepseek_price_update,
                            LlmRate.rate_period == period,
                        )
                    )
                    .scalars()
                    .first()
                )
            if current_rate is None:
                current_rate = LlmRate(
                    id=uuid.uuid4().hex,
                    provider="deepseek",
                    model=model,
                    rate_period=period,
                    effective_from=deepseek_price_update,
                )
                session.add(current_rate)
            current_rate.input_micros_per_million = _micros_per_million(input_rate)
            current_rate.cache_read_micros_per_million = _micros_per_million(cache_read)
            current_rate.output_micros_per_million = _micros_per_million(output_rate)
            current_rate.source_url = deepseek

        sonnet_standard_rate = (
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
        cancelled_sonnet_rate = (
            session.execute(
                select(LlmRate).where(
                    LlmRate.provider == "anthropic",
                    LlmRate.model == "claude-sonnet-5",
                    LlmRate.context_min_tokens == 0,
                    LlmRate.effective_from == sonnet_cancelled_increase,
                )
            )
            .scalars()
            .first()
        )
        if cancelled_sonnet_rate is None:
            if sonnet_standard_rate is not None:
                sonnet_standard_rate.effective_to = None
        else:
            # Do not delete a previously seeded row: usage events may refer to
            # its immutable id. Make both sides of the old boundary carry the
            # now-permanent Standard price instead.
            if sonnet_standard_rate is not None:
                sonnet_standard_rate.effective_to = sonnet_cancelled_increase
            cancelled_sonnet_rate.input_micros_per_million = _micros_per_million(2)
            cancelled_sonnet_rate.cache_read_micros_per_million = _micros_per_million(
                0.2
            )
            cancelled_sonnet_rate.cache_write_micros_per_million = _micros_per_million(
                2.5
            )
            cancelled_sonnet_rate.output_micros_per_million = _micros_per_million(10)
            cancelled_sonnet_rate.tool_micros_per_unit = 10_000
            cancelled_sonnet_rate.source_url = anthropic
        session.commit()
    invalidate_rate_cache(engine)
