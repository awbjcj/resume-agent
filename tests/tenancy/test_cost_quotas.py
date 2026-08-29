import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from resume_agent.config import Settings
from resume_agent.tenancy.context import UserContext, use_context
from resume_agent.tenancy.costs import (
    MeteredUsage,
    calculate_cost,
    find_rate,
    seed_llm_rates,
)
from resume_agent.tenancy.limits import CostRateUnavailableError, enforce_agent_budget
from resume_agent.tenancy.quotas import (
    CostQuotaExceededError,
    GlobalCostQuotaExceededError,
    change_tier,
    charge_shared_cost,
    ensure_quota_account,
    grant_credit,
    quota_snapshot,
    reset_current_period,
)
from resume_agent.tenancy.system_db import (
    LlmRate,
    QuotaTier,
    UsageEvent,
    User,
    init_system_db,
    make_system_engine,
)
from resume_agent.tenancy.workspace import WorkspacePaths

NOW = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)


def _engine(tmp_path):
    engine = make_system_engine(tmp_path)
    init_system_db(engine)
    seed_llm_rates(engine)
    with Session(engine) as session:
        session.add(
            User(
                id="abc123def456",
                username="alice",
                password_hash="hash",
                role="user",
            )
        )
        session.commit()
    return engine


def test_seeded_rate_prices_cache_and_reasoning_without_double_charge(tmp_path):
    engine = _engine(tmp_path)
    usage = MeteredUsage(
        provider="anthropic",
        model="claude-sonnet-5",
        input_tokens=1_000_000,
        output_tokens=500_000,
        cache_read_tokens=250_000,
        cache_write_tokens=100_000,
        reasoning_tokens=400_000,
        total_tokens=1_850_000,
        tool_units=2,
    )

    priced = calculate_cost(engine, usage, now=NOW)

    # $2 input + $5 output + $0.05 cache read + $0.25 cache write +
    # two $0.01 web searches. Reasoning is already part of output_tokens.
    assert priced.total_micros == 7_320_000
    assert priced.tool_micros == 20_000
    assert priced.pricing_status == "PRICED"
    assert priced.rate_id


def test_seeded_model_prices_use_current_provider_rates(tmp_path):
    engine = _engine(tmp_path)
    current = datetime(2026, 8, 27, tzinfo=UTC)

    expected_anthropic = {
        "claude-haiku-4-5": (1_000_000, 100_000, 1_250_000, 5_000_000),
        "claude-sonnet-5": (2_000_000, 200_000, 2_500_000, 10_000_000),
        "claude-opus-4-8": (5_000_000, 500_000, 6_250_000, 25_000_000),
        "claude-opus-5": (5_000_000, 500_000, 6_250_000, 25_000_000),
    }
    for model, expected in expected_anthropic.items():
        rate = find_rate(engine, "anthropic", model, now=current)
        assert rate is not None
        assert (
            rate.input_micros_per_million,
            rate.cache_read_micros_per_million,
            rate.cache_write_micros_per_million,
            rate.output_micros_per_million,
        ) == expected

    expected_openai = {
        "gpt-5.6-sol": (4_000_000, 400_000, 5_000_000, 20_000_000),
        "gpt-5.6-terra": (2_000_000, 200_000, 2_500_000, 12_000_000),
        "gpt-5.6-luna": (200_000, 20_000, 250_000, 1_200_000),
    }
    for model, expected in expected_openai.items():
        rate = find_rate(engine, "openai", model, now=current)
        assert rate is not None
        assert (
            rate.input_micros_per_million,
            rate.cache_read_micros_per_million,
            rate.cache_write_micros_per_million,
            rate.output_micros_per_million,
        ) == expected

    expected_deepseek = {
        "deepseek-v4-flash": (220_000, 7_000, 660_000),
        "deepseek-v4-pro": (660_000, 22_000, 1_980_000),
    }
    for model, expected in expected_deepseek.items():
        rate = find_rate(engine, "deepseek", model, now=current)
        assert rate is not None
        assert (
            rate.input_micros_per_million,
            rate.cache_read_micros_per_million,
            rate.output_micros_per_million,
        ) == expected

    # Google publishes Gemini 3.6 Flash at $0.75/M input, $0.075/M cached
    # input, and $3.75/M output (including thinking). Gemini 3.1 Flash Lite
    # is a catalog option and therefore must have an active metering rate too.
    expected_gemini = {
        "gemini-3.6-flash": (750_000, 75_000, 3_750_000, 14_000),
        "gemini-3.1-flash-lite": (250_000, 25_000, 1_500_000, 14_000),
    }
    for model, expected in expected_gemini.items():
        rate = find_rate(engine, "gemini", model, now=current)
        assert rate is not None
        assert (
            rate.input_micros_per_million,
            rate.cache_read_micros_per_million,
            rate.output_micros_per_million,
            rate.tool_micros_per_unit,
        ) == expected


def test_seed_corrects_previously_scheduled_sonnet_increase(tmp_path):
    engine = _engine(tmp_path)
    cutoff = datetime(2026, 9, 1, tzinfo=UTC)
    current = find_rate(
        engine,
        "anthropic",
        "claude-sonnet-5",
        now=datetime(2026, 8, 31, tzinfo=UTC),
    )
    assert current is not None

    with Session(engine) as session:
        stored_current = session.get(LlmRate, current.id)
        assert stored_current is not None
        stored_current.effective_to = cutoff
        session.add(
            LlmRate(
                id="cancelled-sonnet-increase",
                provider="anthropic",
                model="claude-sonnet-5",
                input_micros_per_million=3_000_000,
                cache_read_micros_per_million=300_000,
                cache_write_micros_per_million=3_750_000,
                output_micros_per_million=15_000_000,
                tool_micros_per_unit=10_000,
                effective_from=cutoff,
                source_url="https://platform.claude.com/docs/en/about-claude/pricing",
            )
        )
        session.commit()

    seed_llm_rates(engine)

    corrected = find_rate(
        engine,
        "anthropic",
        "claude-sonnet-5",
        now=cutoff,
    )
    assert corrected is not None
    assert corrected.id == "cancelled-sonnet-increase"
    assert (
        corrected.input_micros_per_million,
        corrected.cache_read_micros_per_million,
        corrected.cache_write_micros_per_million,
        corrected.output_micros_per_million,
    ) == (2_000_000, 200_000, 2_500_000, 10_000_000)


def test_deepseek_switches_to_peak_off_peak_rates_after_cutover(tmp_path):
    engine = _engine(tmp_path)

    # Just before the 2026-08-16T16:00Z cutover, the flat legacy rate is
    # still active regardless of hour.
    just_before = datetime(2026, 8, 16, 15, 59, tzinfo=UTC)
    rate = find_rate(engine, "deepseek", "deepseek-v4-flash", now=just_before)
    assert rate is not None
    assert rate.rate_period is None
    assert rate.input_micros_per_million == 140_000

    expected = {
        ("deepseek-v4-flash", "off_peak"): (220_000, 7_000, 660_000),
        ("deepseek-v4-flash", "peak"): (440_000, 14_000, 1_320_000),
        ("deepseek-v4-pro", "off_peak"): (660_000, 22_000, 1_980_000),
        ("deepseek-v4-pro", "peak"): (1_320_000, 44_000, 3_960_000),
    }
    # hour=2 -> peak (01:00-04:00), hour=12 -> off-peak.
    moments = {
        "peak": datetime(2026, 8, 17, 2, 0, tzinfo=UTC),
        "off_peak": datetime(2026, 8, 17, 12, 0, tzinfo=UTC),
    }
    for (model, period), micros in expected.items():
        rate = find_rate(engine, "deepseek", model, now=moments[period])
        assert rate is not None
        assert rate.rate_period == period
        assert (
            rate.input_micros_per_million,
            rate.cache_read_micros_per_million,
            rate.output_micros_per_million,
        ) == micros


def test_deepseek_peak_windows_are_half_open(tmp_path):
    engine = _engine(tmp_path)
    # Peak bands are [01:00, 04:00) and [06:00, 10:00); the end hour of each
    # band is already off-peak, and the start hour is already peak.
    off_peak_boundaries = (4, 10, 0, 5, 11)
    peak_boundaries = (1, 3, 6, 9)
    for hour in off_peak_boundaries:
        moment = datetime(2026, 8, 17, hour, 0, tzinfo=UTC)
        rate = find_rate(engine, "deepseek", "deepseek-v4-flash", now=moment)
        assert rate is not None
        assert rate.rate_period == "off_peak", hour
    for hour in peak_boundaries:
        moment = datetime(2026, 8, 17, hour, 0, tzinfo=UTC)
        rate = find_rate(engine, "deepseek", "deepseek-v4-flash", now=moment)
        assert rate is not None
        assert rate.rate_period == "peak", hour


def test_deepseek_weekends_are_off_peak_in_beijing_time_after_rule_change(tmp_path):
    engine = _engine(tmp_path)

    # The weekend rule begins at 2026-08-29 00:00 Beijing time. The preceding
    # Saturday still used the prior daily peak window, preserving history.
    legacy_saturday = find_rate(
        engine,
        "deepseek",
        "deepseek-v4-flash",
        now=datetime(2026, 8, 22, 2, 0, tzinfo=UTC),
    )
    assert legacy_saturday is not None
    assert legacy_saturday.rate_period == "peak"

    # 02:00 and 07:00 UTC are weekday peak hours, but they are Saturday morning
    # and afternoon in Beijing, so both use the all-day off-peak price.
    for hour in (2, 7):
        weekend_rate = find_rate(
            engine,
            "deepseek",
            "deepseek-v4-flash",
            now=datetime(2026, 8, 29, hour, 0, tzinfo=UTC),
        )
        assert weekend_rate is not None
        assert weekend_rate.rate_period == "off_peak"
        assert (
            weekend_rate.input_micros_per_million,
            weekend_rate.cache_read_micros_per_million,
            weekend_rate.output_micros_per_million,
        ) == (220_000, 7_000, 660_000)

    weekday_rate = find_rate(
        engine,
        "deepseek",
        "deepseek-v4-flash",
        now=datetime(2026, 8, 31, 2, 0, tzinfo=UTC),
    )
    assert weekday_rate is not None
    assert weekday_rate.rate_period == "peak"


def test_embedding_rate_is_seeded_for_shared_key_metering(tmp_path):
    engine = _engine(tmp_path)
    priced = calculate_cost(
        engine,
        MeteredUsage(
            provider="openai",
            model="text-embedding-3-small",
            input_tokens=1_000_000,
        ),
        now=datetime(2026, 8, 2, tzinfo=UTC),
    )

    assert priced.pricing_status == "PRICED"
    assert priced.total_micros == 20_000


def test_openai_price_version_preserves_previous_gpt_5_6_rate(tmp_path):
    engine = _engine(tmp_path)
    usage = MeteredUsage(
        provider="openai",
        model="gpt-5.6-terra",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )

    before_update = calculate_cost(engine, usage, now=NOW)
    after_update = calculate_cost(engine, usage, now=datetime(2026, 8, 2, tzinfo=UTC))

    assert before_update.total_micros == 17_500_000
    assert after_update.total_micros == 14_000_000
    assert before_update.rate_id != after_update.rate_id


def test_openai_sol_price_version_preserves_the_pre_reduction_rate(tmp_path):
    engine = _engine(tmp_path)
    usage = MeteredUsage(
        provider="openai",
        model="gpt-5.6-sol",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )

    before_update = calculate_cost(
        engine, usage, now=datetime(2026, 8, 26, 23, 59, tzinfo=UTC)
    )
    after_update = calculate_cost(
        engine, usage, now=datetime(2026, 8, 27, tzinfo=UTC)
    )

    assert before_update.total_micros == 35_000_000
    assert after_update.total_micros == 24_000_000
    assert before_update.rate_id != after_update.rate_id


def test_gemini_price_version_preserves_the_pre_update_flash_rate(tmp_path):
    engine = _engine(tmp_path)
    usage = MeteredUsage(
        provider="gemini",
        model="gemini-3.6-flash",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )

    before_update = calculate_cost(engine, usage, now=NOW)
    after_update = calculate_cost(
        engine, usage, now=datetime(2026, 8, 15, tzinfo=UTC)
    )

    assert before_update.total_micros == 9_000_000
    assert after_update.total_micros == 4_500_000
    assert before_update.rate_id != after_update.rate_id


def test_seed_corrects_previously_written_batch_rate(tmp_path):
    engine = _engine(tmp_path)
    current = datetime(2026, 8, 2, tzinfo=UTC)
    rate = find_rate(engine, "openai", "gpt-5.6-terra", now=current)
    assert rate is not None
    with Session(engine) as session:
        stored_rate = session.get(LlmRate, rate.id)
        assert stored_rate is not None
        stored_rate.input_micros_per_million = 1_000_000
        stored_rate.cache_read_micros_per_million = 100_000
        stored_rate.cache_write_micros_per_million = 1_250_000
        stored_rate.output_micros_per_million = 6_000_000
        session.commit()

    seed_llm_rates(engine)

    corrected = find_rate(engine, "openai", "gpt-5.6-terra", now=current)
    assert corrected is not None
    assert (
        corrected.input_micros_per_million,
        corrected.cache_read_micros_per_million,
        corrected.cache_write_micros_per_million,
        corrected.output_micros_per_million,
    ) == (2_000_000, 200_000, 2_500_000, 12_000_000)


def test_unknown_rate_is_explicit(tmp_path):
    engine = _engine(tmp_path)
    priced = calculate_cost(
        engine,
        MeteredUsage(provider="openai", model="custom-model", input_tokens=10),
        now=NOW,
    )
    assert priced.total_micros is None
    assert priced.pricing_status == "RATE_UNAVAILABLE"


def test_free_period_credit_reset_and_bounded_overage(tmp_path):
    engine = _engine(tmp_path)
    account = ensure_quota_account(engine, "abc123def456", now=NOW)
    assert account.tier_id == "FREE"
    assert account.period_end == datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
    assert account.allowance_micros == 1_000_000

    charge_shared_cost(engine, "abc123def456", 900_000, now=NOW)
    grant_credit(engine, "abc123def456", 200_000, now=NOW)
    charge_shared_cost(engine, "abc123def456", 400_000, now=NOW)

    snapshot = quota_snapshot(engine, "abc123def456", now=NOW)
    assert snapshot.spent_micros == 1_300_000
    assert snapshot.credit_balance_micros == 0
    assert snapshot.credit_spent_micros == 200_000
    assert snapshot.overage_micros == 100_000
    assert snapshot.remaining_micros == 0
    with pytest.raises(CostQuotaExceededError):
        charge_shared_cost(engine, "abc123def456", 1, now=NOW, preflight=True)

    reset_current_period(engine, "abc123def456", now=NOW)
    reset = quota_snapshot(engine, "abc123def456", now=NOW)
    assert reset.period_end == snapshot.period_end
    assert reset.spent_micros == 0
    assert reset.credit_balance_micros == 200_000
    assert reset.remaining_micros == 1_200_000


def test_tier_change_starts_monthly_period_and_preserves_credit(tmp_path):
    engine = _engine(tmp_path)
    ensure_quota_account(engine, "abc123def456", now=NOW)
    grant_credit(engine, "abc123def456", 500_000, now=NOW)

    changed = change_tier(engine, "abc123def456", "SUBSCRIBER", now=NOW)

    assert changed.tier_id == "SUBSCRIBER"
    assert changed.allowance_micros == 20_000_000
    assert changed.credit_balance_micros == 500_000
    assert changed.period_start == NOW
    assert changed.period_end == datetime(2026, 8, 30, 12, 0, tzinfo=UTC)


def test_custom_tier_zero_is_zero_not_unlimited(tmp_path):
    engine = _engine(tmp_path)
    with Session(engine) as session:
        session.add(
            QuotaTier(
                id="NO_SPEND",
                name="No spend",
                cycle_unit="WEEK",
                cycle_count=1,
                allowance_micros=0,
            )
        )
        session.commit()
    change_tier(engine, "abc123def456", "NO_SPEND", now=NOW)
    with pytest.raises(CostQuotaExceededError):
        charge_shared_cost(engine, "abc123def456", 1, now=NOW, preflight=True)


def test_month_end_anchor_clamps_without_drifting(tmp_path):
    engine = _engine(tmp_path)
    jan_31 = datetime(2026, 1, 31, 9, 30, tzinfo=UTC)
    ensure_quota_account(engine, "abc123def456", now=jan_31)
    feb = change_tier(engine, "abc123def456", "SUBSCRIBER", now=jan_31)
    assert feb.period_end == datetime(2026, 2, 28, 9, 30, tzinfo=UTC)
    rolled = quota_snapshot(
        engine,
        "abc123def456",
        now=datetime(2026, 3, 1, tzinfo=UTC),
    )
    assert rolled.period_end == datetime(2026, 3, 31, 9, 30, tzinfo=UTC)


def test_sonnet_standard_rate_does_not_increase_in_september(tmp_path):
    engine = _engine(tmp_path)
    usage = MeteredUsage(
        provider="anthropic",
        model="claude-sonnet-5",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    july = calculate_cost(engine, usage, now=NOW)
    september = calculate_cost(engine, usage, now=datetime(2026, 9, 2, tzinfo=UTC))
    assert july.total_micros == 12_000_000
    assert september.total_micros == 12_000_000
    assert july.rate_id == september.rate_id


def test_enforcement_rejects_unknown_shared_rate_but_allows_byok(tmp_path):
    engine = _engine(tmp_path)
    context = UserContext(
        user_id="abc123def456",
        username="alice",
        role="user",
        paths=WorkspacePaths(tmp_path / "users" / "abc123def456"),
        settings=Settings(_env_file=None, cost_quota_enforcement="enforce"),  # type: ignore[call-arg]
        engine=None,
        system_engine=engine,
        own_key_providers=frozenset(),
    )
    agent = SimpleNamespace(model=SimpleNamespace(id="custom-model", provider="openai"))
    with use_context(context), pytest.raises(CostRateUnavailableError):
        enforce_agent_budget(agent, now=NOW)
    with use_context(
        UserContext(
            **{
                **context.__dict__,
                "own_key_providers": frozenset({"openai"}),
            }
        )
    ):
        enforce_agent_budget(agent, now=NOW)


def test_concurrent_in_flight_charges_create_bounded_overage_atomically(tmp_path):
    engine = _engine(tmp_path)
    ensure_quota_account(engine, "abc123def456", now=NOW)
    charge_shared_cost(engine, "abc123def456", 900_000, now=NOW)
    barrier = threading.Barrier(2)

    def finish_call() -> None:
        barrier.wait(timeout=5)
        charge_shared_cost(engine, "abc123def456", 200_000, now=NOW)

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda _index: finish_call(), range(2)))

    snapshot = quota_snapshot(engine, "abc123def456", now=NOW)
    assert snapshot.spent_micros == 1_300_000
    assert snapshot.overage_micros == 300_000
    with pytest.raises(CostQuotaExceededError):
        charge_shared_cost(engine, "abc123def456", 0, now=NOW, preflight=True)


def test_admin_shared_usage_is_bounded_by_global_cost_quota(tmp_path):
    engine = _engine(tmp_path)
    with Session(engine) as session:
        session.add(
            UsageEvent(
                user_id="admin000001",
                ts=NOW,
                provider="anthropic",
                model="claude-haiku-4-5",
                cost_micros=500_000_000,
                quota_cost_micros=500_000_000,
                pricing_status="PRICED",
            )
        )
        session.commit()
    context = UserContext(
        user_id="admin000001",
        username="owner",
        role="admin",
        paths=WorkspacePaths(tmp_path / "users" / "admin000001"),
        settings=Settings(_env_file=None, cost_quota_enforcement="enforce"),  # type: ignore[call-arg]
        engine=None,
        system_engine=engine,
        own_key_providers=frozenset(),
    )
    agent = SimpleNamespace(
        model=SimpleNamespace(id="claude-haiku-4-5", provider="anthropic")
    )
    with use_context(context), pytest.raises(GlobalCostQuotaExceededError):
        enforce_agent_budget(agent, now=NOW)


def test_admin_usage_counts_toward_global_cost_quota_for_other_users(tmp_path):
    engine = _engine(tmp_path)
    with Session(engine) as session:
        session.add(
            User(
                id="admin000001",
                username="owner",
                password_hash="hash",
                role="admin",
            )
        )
        session.add(
            UsageEvent(
                user_id="admin000001",
                ts=NOW,
                provider="anthropic",
                model="claude-haiku-4-5",
                cost_micros=500_000_000,
                quota_cost_micros=500_000_000,
                pricing_status="PRICED",
            )
        )
        session.commit()
    context = UserContext(
        user_id="abc123def456",
        username="alice",
        role="user",
        paths=WorkspacePaths(tmp_path / "users" / "abc123def456"),
        settings=Settings(
            _env_file=None,  # type: ignore[call-arg]
            cost_quota_enforcement="enforce",
            global_monthly_cost_quota_micros=1,
        ),
        engine=None,
        system_engine=engine,
        own_key_providers=frozenset(),
    )
    agent = SimpleNamespace(
        model=SimpleNamespace(id="claude-haiku-4-5", provider="anthropic")
    )
    with use_context(context), pytest.raises(GlobalCostQuotaExceededError):
        enforce_agent_budget(agent, now=NOW)
