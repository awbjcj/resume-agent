from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import threading
from types import SimpleNamespace
import pytest
from sqlalchemy.orm import Session

from resume_agent.tenancy.costs import MeteredUsage, calculate_cost, seed_llm_rates
from resume_agent.config import Settings
from resume_agent.tenancy.context import UserContext, use_context
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
    QuotaTier,
    UsageEvent,
    User,
    init_system_db,
    make_system_engine,
)
from resume_agent.tenancy.workspace import WorkspacePaths


NOW = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)


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
    assert account.period_end == datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)
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
    assert changed.period_end == datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


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
    jan_31 = datetime(2026, 1, 31, 9, 30, tzinfo=timezone.utc)
    ensure_quota_account(engine, "abc123def456", now=jan_31)
    feb = change_tier(engine, "abc123def456", "SUBSCRIBER", now=jan_31)
    assert feb.period_end == datetime(2026, 2, 28, 9, 30, tzinfo=timezone.utc)
    rolled = quota_snapshot(
        engine,
        "abc123def456",
        now=datetime(2026, 3, 1, tzinfo=timezone.utc),
    )
    assert rolled.period_end == datetime(2026, 3, 31, 9, 30, tzinfo=timezone.utc)


def test_effective_rate_version_preserves_historical_sonnet_price(tmp_path):
    engine = _engine(tmp_path)
    usage = MeteredUsage(
        provider="anthropic",
        model="claude-sonnet-5",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )
    july = calculate_cost(engine, usage, now=NOW)
    september = calculate_cost(
        engine, usage, now=datetime(2026, 9, 2, tzinfo=timezone.utc)
    )
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
        settings=Settings(_env_file=None, cost_quota_enforcement="enforce"),
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


def test_admin_is_user_exempt_but_still_stopped_by_platform_cap(tmp_path):
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
        settings=Settings(_env_file=None, cost_quota_enforcement="enforce"),
        engine=None,
        system_engine=engine,
        own_key_providers=frozenset(),
    )
    agent = SimpleNamespace(
        model=SimpleNamespace(id="claude-haiku-4-5", provider="anthropic")
    )
    with use_context(context), pytest.raises(GlobalCostQuotaExceededError):
        enforce_agent_budget(agent, now=NOW)
