from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from agno.metrics import ModelMetrics, RunMetrics
from sqlalchemy import select
from sqlalchemy.orm import Session

from resume_agent.config import Settings
from resume_agent.llm_runner import AgentRunner
from resume_agent.tenancy.context import UserContext, use_context
from resume_agent.tenancy.limits import (
    BudgetExceededError,
    DEFAULT_MAX_ACTIVE_JOBS,
    DEFAULT_MAX_CONCURRENT_RUNS,
    DEFAULT_WEEKLY_TOKEN_BUDGET,
    active_limit,
    enforce_active_budget,
    enforce_budget,
    weekly_usage,
)
from resume_agent.tenancy.system_db import (
    UsageEvent,
    User,
    init_system_db,
    make_system_engine,
)
from resume_agent.tenancy.workspace import WorkspacePaths


class FakeAgent:
    model = SimpleNamespace(id="claude-test")

    def run(self, _prompt):
        return SimpleNamespace(
            metrics=SimpleNamespace(
                input_tokens=100,
                output_tokens=20,
                cache_read_tokens=10,
                cache_creation_tokens=4,
            )
        )

    async def arun(self, prompt):
        return self.run(prompt)


def _context(tmp_path, engine, *, own_keys=frozenset(), role="user"):
    return UserContext(
        user_id="abc123def456",
        username="alice",
        role=role,
        paths=WorkspacePaths(tmp_path / "users" / "abc123def456"),
        settings=Settings(
            _env_file=None,  # type: ignore[call-arg]
            anthropic_api_key="user-key" if "anthropic" in own_keys else "",
            openai_api_key="",
            gemini_api_key="",
            deepseek_api_key="",
        ),
        engine=None,
        system_engine=engine,
        own_key_providers=own_keys,
    )


@pytest.mark.asyncio
async def test_agent_runner_records_sync_and_async_usage(tmp_path):
    engine = make_system_engine(tmp_path)
    init_system_db(engine)
    runner = AgentRunner(FakeAgent())
    with use_context(_context(tmp_path, engine)):
        runner.run("sync")
        await runner.arun("async")
    with Session(engine) as session:
        events = session.execute(select(UsageEvent)).scalars().all()
    assert len(events) == 2
    assert events[0].weighted_total == 100 + 20 * 3 + 10 * 0.1 + 4 * 1.25
    assert events[0].own_key is False
    engine.dispose()


def test_open_signup_account_cannot_spend_shared_platform_key(tmp_path):
    engine = make_system_engine(tmp_path)
    init_system_db(engine)
    with Session(engine) as session:
        session.add(
            User(
                id="abc123def456",
                username="alice",
                password_hash="hash",
                role="user",
                shared_key_access=False,
            )
        )
        session.commit()
    with use_context(_context(tmp_path, engine)):
        with pytest.raises(BudgetExceededError, match="shared platform models"):
            AgentRunner(FakeAgent()).run("blocked")
    engine.dispose()


def test_open_signup_account_can_use_its_own_provider_key(tmp_path):
    engine = make_system_engine(tmp_path)
    init_system_db(engine)
    with Session(engine) as session:
        session.add(
            User(
                id="abc123def456",
                username="alice",
                password_hash="hash",
                role="user",
                shared_key_access=False,
            )
        )
        session.commit()
    with use_context(_context(tmp_path, engine, own_keys=frozenset({"anthropic"}))):
        AgentRunner(FakeAgent()).run("allowed")
    with Session(engine) as session:
        assert session.execute(select(UsageEvent)).scalar_one().own_key is True
    engine.dispose()


def test_global_platform_budget_stops_new_shared_key_calls(tmp_path):
    engine = make_system_engine(tmp_path)
    init_system_db(engine)
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        session.add(
            User(
                id="abc123def456",
                username="alice",
                password_hash="hash",
                role="user",
                shared_key_access=True,
            )
        )
        session.add(
            UsageEvent(user_id="someoneelse", ts=now, weighted_total=50_000_001)
        )
        session.commit()
    with use_context(_context(tmp_path, engine)):
        with pytest.raises(BudgetExceededError, match="platform weekly"):
            AgentRunner(FakeAgent()).run("blocked")
    engine.dispose()


def test_usage_writes_to_context_engine_and_tracks_own_key(tmp_path):
    first = make_system_engine(tmp_path / "first")
    second = make_system_engine(tmp_path / "second")
    init_system_db(first)
    init_system_db(second)
    runner = AgentRunner(FakeAgent())
    with use_context(_context(tmp_path, second, own_keys=frozenset({"anthropic"}))):
        runner.run("call")
    with Session(first) as session:
        assert session.execute(select(UsageEvent)).scalars().all() == []
    with Session(second) as session:
        assert session.execute(select(UsageEvent)).scalar_one().own_key is True
    first.dispose()
    second.dispose()


def test_usage_records_each_agno_model_detail_with_exact_provider_identity(tmp_path):
    engine = make_system_engine(tmp_path)
    init_system_db(engine)
    response = SimpleNamespace(
        metrics=RunMetrics(
            details={
                "model": [
                    ModelMetrics(
                        id="gpt-5.6-terra",
                        provider="OpenAI",
                        input_tokens=12,
                        output_tokens=5,
                        reasoning_tokens=3,
                    )
                ],
                "output_model": [
                    ModelMetrics(
                        id="claude-haiku-4-5",
                        provider="Anthropic",
                        input_tokens=7,
                        output_tokens=2,
                    )
                ],
            }
        )
    )
    agent = SimpleNamespace(model=SimpleNamespace(id="bare-id"))
    with use_context(_context(tmp_path, engine, own_keys=frozenset({"openai"}))):
        from resume_agent.tenancy.usage import record_call

        record_call(agent, response)
    with Session(engine) as session:
        events = (
            session.execute(select(UsageEvent).order_by(UsageEvent.id)).scalars().all()
        )
    assert [(event.provider, event.model) for event in events] == [
        ("openai", "gpt-5.6-terra"),
        ("anthropic", "claude-haiku-4-5"),
    ]
    assert events[0].own_key is True
    assert events[0].reasoning_tokens == 3
    assert events[1].reasoning_mode == "OUTPUT_MODEL"
    engine.dispose()


def test_budget_window_exemptions_and_active_guard(tmp_path):
    engine = make_system_engine(tmp_path)
    init_system_db(engine)
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        session.add(
            User(
                id="abc123def456",
                username="alice",
                password_hash="hash",
                role="user",
                weekly_token_budget=100,
            )
        )
        session.add(UsageEvent(user_id="abc123def456", ts=now, weighted_total=101))
        session.add(
            UsageEvent(
                user_id="abc123def456",
                ts=now,
                weighted_total=999,
                own_key=True,
            )
        )
        session.add(
            UsageEvent(
                user_id="abc123def456",
                ts=now - timedelta(days=8),
                weighted_total=999,
            )
        )
        session.commit()
    assert weekly_usage(engine, "abc123def456", now=now) == 101
    with pytest.raises(BudgetExceededError):
        enforce_budget(
            engine,
            user_id="abc123def456",
            role="user",
            budget_override=100,
            now=now,
        )
    enforce_budget(
        engine,
        user_id="abc123def456",
        role="admin",
        budget_override=1,
        now=now,
    )
    with use_context(_context(tmp_path, engine)):
        with pytest.raises(BudgetExceededError):
            enforce_active_budget(now=now)
    engine.dispose()


def test_default_budget_constant_is_shipped_value():
    assert DEFAULT_WEEKLY_TOKEN_BUDGET == 10_000_000


def test_admin_active_job_and_concurrency_limits_are_unlimited(tmp_path):
    engine = make_system_engine(tmp_path)
    init_system_db(engine)
    with Session(engine) as session:
        session.add(
            User(
                id="abc123def456",
                username="alice",
                password_hash="hash",
                role="admin",
                max_active_jobs=1,
                max_concurrent_runs=1,
            )
        )
        session.commit()

    with use_context(_context(tmp_path, engine, role="admin")):
        assert active_limit("max_active_jobs", DEFAULT_MAX_ACTIVE_JOBS) == 0
        assert active_limit("max_concurrent_runs", DEFAULT_MAX_CONCURRENT_RUNS) == 0

    engine.dispose()
