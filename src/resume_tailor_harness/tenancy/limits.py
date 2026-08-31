from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from resume_tailor_harness.tenancy.context import current_context
from resume_tailor_harness.tenancy.costs import normalize_provider
from resume_tailor_harness.tenancy.quotas import (
    charge_shared_cost,
)
from resume_tailor_harness.tenancy.system_db import SystemSetting, UsageEvent, User

DEFAULT_WEEKLY_TOKEN_BUDGET = 10_000_000
DEFAULT_MAX_ACTIVE_JOBS = 2_000
DEFAULT_MAX_CONCURRENT_RUNS = 2
DEFAULT_GLOBAL_WEEKLY_TOKEN_BUDGET = 50_000_000
BUDGET_WINDOW = timedelta(days=7)


class BudgetExceededError(RuntimeError):
    code = "BUDGET_EXCEEDED"


class CostRateUnavailableError(RuntimeError):
    code = "COST_RATE_UNAVAILABLE"


def _agent_identity(agent: object) -> tuple[str, str]:
    model = getattr(agent, "model", None)
    model_id = str(getattr(model, "id", None) or getattr(agent, "model_id", None) or "")
    provider: object = getattr(model, "provider", None)
    get_provider = getattr(model, "get_provider", None)
    if not provider and callable(get_provider):
        provider = get_provider()
    if not provider and model_id:
        from resume_tailor_harness.llm_runner import split_provider

        provider, model_id = split_provider(model_id)
    return normalize_provider(str(provider or "")), model_id


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


def global_weekly_usage(engine: Engine, *, now: datetime | None = None) -> float:
    moment = now or datetime.now(timezone.utc)
    with Session(engine) as session:
        total = session.execute(
            select(func.coalesce(func.sum(UsageEvent.weighted_total), 0.0)).where(
                UsageEvent.own_key.is_(False),
                UsageEvent.ts >= moment - BUDGET_WINDOW,
            )
        ).scalar_one()
    return float(total)


def selected_key_is_own(provider: str, agent: object | None = None) -> bool:
    """Return whether the active call selected the user's provider key."""

    context = current_context()
    if context is None:
        return False
    model = getattr(agent, "model", None)
    if model is not None:
        selected_model = context.selected_model_own_keys.get(id(model))
        if selected_model is not None:
            return selected_model
    selected = context.selected_own_key_providers.get(provider)
    return provider in context.own_key_providers if selected is None else selected


def shared_key_available(
    provider: str, model_id: str, *, now: datetime | None = None
) -> bool:
    """Whether a Railway/provider key may fund the active user's next call.

    Kept as a named predicate for callers that want the question without the
    key, but the policy itself now lives in one place — see
    ``tenancy/spend.py``, which derives this and the typed enforcement error
    from a single evaluation so the two cannot drift apart.
    """
    from resume_tailor_harness.tenancy.spend import _shared_denial

    context = current_context()
    if context is None or provider not in context.platform_provider_keys:
        return False
    if context.system_engine is None:
        return True
    return _shared_denial(context, provider, model_id, now=now) is None


def enforce_agent_budget(agent: object, *, now: datetime | None = None) -> None:
    """Enforce account eligibility plus user/global spend before an LLM call.

    ``AgentRunner`` goes through ``SpendGate.open`` directly (it needs the key
    as well as the verdict). This remains the entry point for callers that
    already hold a key — direct transcription, principally — and delegates to
    the same gate, so it shares the same per-phase cached decision.
    """
    from resume_tailor_harness.tenancy.spend import SpendGate

    context = current_context()
    if context is None or context.system_engine is None:
        return
    provider, model_id = _agent_identity(agent)
    if provider and selected_key_is_own(provider, agent):
        return
    prefixed = model_id if provider in ("", "anthropic") else f"{provider}:{model_id}"
    SpendGate().open(prefixed, now=now)


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
    if context.settings.cost_quota_enforcement == "enforce":
        if not context.is_admin:
            charge_shared_cost(
                context.system_engine,
                context.user_id,
                0,
                now=now,
                preflight=True,
            )
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
