from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from resume_agent.tenancy.context import current_context
from resume_agent.tenancy.system_db import SystemSetting, UsageEvent, User

DEFAULT_WEEKLY_TOKEN_BUDGET = 10_000_000
DEFAULT_MAX_ACTIVE_JOBS = 2_000
DEFAULT_MAX_CONCURRENT_RUNS = 2
BUDGET_WINDOW = timedelta(days=7)


class BudgetExceededError(RuntimeError):
    code = "BUDGET_EXCEEDED"


def system_default(engine: Engine, key: str, fallback: int) -> int:
    with Session(engine) as session:
        setting = session.get(SystemSetting, key)
    if setting is None:
        return fallback
    try:
        value = int(setting.value)
    except ValueError:
        return fallback
    return value if value >= 0 else fallback


def resolve_limit(override: int | None, default: int) -> int:
    return default if override is None else override


def weekly_usage(engine: Engine, user_id: str, *, now: datetime | None = None) -> float:
    moment = now or datetime.now(timezone.utc)
    with Session(engine) as session:
        total = session.execute(
            select(func.coalesce(func.sum(UsageEvent.weighted_total), 0.0)).where(
                UsageEvent.user_id == user_id,
                UsageEvent.own_key.is_(False),
                UsageEvent.ts >= moment - BUDGET_WINDOW,
            )
        ).scalar_one()
    return float(total)


def enforce_budget(
    engine: Engine,
    *,
    user_id: str,
    role: str,
    budget_override: int | None,
    now: datetime | None = None,
) -> None:
    if role == "admin":
        return
    budget = resolve_limit(
        budget_override,
        system_default(engine, "weekly_token_budget", DEFAULT_WEEKLY_TOKEN_BUDGET),
    )
    if budget == 0:
        return
    spent = weekly_usage(engine, user_id, now=now)
    if spent >= budget:
        raise BudgetExceededError(
            f"weekly token budget exhausted ({spent:,.0f} of {budget:,} weighted tokens)"
        )


def enforce_active_budget(*, now: datetime | None = None) -> None:
    context = current_context()
    if context is None or context.system_engine is None:
        return
    with Session(context.system_engine) as session:
        user = session.get(User, context.user_id)
        override = user.weekly_token_budget if user is not None else None
    enforce_budget(
        context.system_engine,
        user_id=context.user_id,
        role=context.role,
        budget_override=override,
        now=now,
    )


def active_limit(key: str, fallback: int) -> int | None:
    """Resolve the active user's limit, with administrators always unlimited."""
    context = current_context()
    if context is None or context.system_engine is None:
        return None
    if context.is_admin:
        return 0
    with Session(context.system_engine) as session:
        user = session.get(User, context.user_id)
        override = getattr(user, key, None) if user is not None else None
    return resolve_limit(override, system_default(context.system_engine, key, fallback))
