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


def test_seeded_model_prices_use_current_openai_and_deepseek_rates(tmp_path):
    engine = _engine(tmp_path)
    current = datetime(2026, 8, 2, tzinfo=UTC)

    expected_openai = {
        "gpt-5.6-sol": (5_000_000, 500_000, 6_250_000, 30_000_000),
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
        "deepseek-v4-flash": (140_000, 2_800, 280_000),
        "deepseek-v4-pro": (435_000, 3_625, 870_000),
    }
    for model, expected in expected_deepseek.items():
        rate = find_rate(engine, "deepseek", model, now=current)
        assert rate is not None
        assert (
            rate.input_micros_per_million,
            rate.cache_read_micros_per_million,
            rate.output_micros_per_million,
        ) == expected


def test_openai_price_version_preserves_previous_gpt_5_6_rate(tmp_path):
    engine = _engine(tmp_path)
    usage = MeteredUsage(
        provider="openai",
        model="gpt-5.6-terra",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )

    before_update = calculate_cost(engine, usage, now=NOW)
    after_update = calculate_cost(
        engine, usage, now=datetime(2026, 8, 2, tzinfo=UTC)
    )

    assert before_update.total_micros == 17_500_000
    assert after_update.total_micros == 14_000_000
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


def test_effective_rate_version_preserves_historical_sonnet_price(tmp_path):
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
    assert september.total_micros == 18_000_000
    assert july.rate_id != september.rate_id


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
