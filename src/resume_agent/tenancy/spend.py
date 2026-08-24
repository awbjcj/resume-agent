"""The one seam that resolves key selection and budget policy for a phase.

Before this module, the same five facts — the user row, shared-key eligibility,
the active rate, the remaining allowance, the platform cap — were derived
independently in three places on **every** LLM call:

* ``resolve_api_key`` → ``shared_key_available`` (asking "which key?")
* ``enforce_agent_budget`` (asking "may I spend?")
* ``record_call`` → ``charge_shared_cost`` (settling)

That is a shallow interface over an expensive implementation: the caller says
"give me a key" and pays for a full policy evaluation, then says "may I spend"
and pays for it again. Measured, it cost 22.2 SQLite statements and one
exclusive ``BEGIN IMMEDIATE`` per call, all of it synchronous and all of it on
the event loop that the concurrent fan-out shares.

The fix is not a faster query, it is a correct unit. A budget is a property of
a **phase**, not of a call — which is what ``CONTEXT.md`` always claimed — so
one evaluation is cached on the active :class:`UserContext` behind a short TTL
and reused by every call in that phase. The decision is dropped immediately if
a charge exhausts the allowance, so the window never lets a call through that
the previous call's cost should have stopped.

**Behaviour is deliberately unchanged.** Every existing error type is raised
from the same conditions:

* the user's own key is preferred when shared funding is unavailable, and no
  error is raised, exactly as ``resolve_api_key`` did;
* an error is raised only when there is no own key to fall back on, exactly as
  ``enforce_agent_budget`` did;
* administrators are exempt from the **per-user allowance** and remain bound by
  the **platform-wide cap** (ADR-0009 Amendment 2, ADR-0010 §26).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from resume_agent.config import Settings
from resume_agent.tenancy.context import UserContext, current_context
from resume_agent.tenancy.costs import has_active_rate
from resume_agent.tenancy.limits import (
    DEFAULT_WEEKLY_TOKEN_BUDGET,
    BudgetExceededError,
    CostRateUnavailableError,
    global_weekly_usage,
    resolve_limit,
    system_default,
    weekly_usage,
)
from resume_agent.tenancy.quotas import (
    DEFAULT_GLOBAL_MONTHLY_COST_QUOTA_MICROS,
    CostQuotaExceededError,
    GlobalCostQuotaExceededError,
    QuotaSnapshot,
    charge_shared_cost,
    global_monthly_cost,
)
from resume_agent.tenancy.system_db import User

__all__ = [
    "SpendDecision",
    "SpendGate",
    "invalidate_spend_decisions",
]


@dataclass(frozen=True)
class SpendDecision:
    """Which key funds this call, where it is sent, and why."""

    api_key: str
    own_key: bool
    provider: str
    model: str
    reason: str
    # Non-None only for subscription-routed calls. Carried here rather than
    # derived separately by ``build_model`` so the endpoint and the credential
    # can never come from two different evaluations of the same config -- the
    # same reason key selection and budget share this class (ADR-0009).
    base_url: str | None = None


@dataclass
class _CachedDecision:
    """One resolved decision, its fatal error, and its remaining headroom."""

    stamped: float
    decision: SpendDecision
    fatal: RuntimeError | None
    headroom: float | None
    unit: str = "weighted"


def _settled(decision: SpendDecision) -> _CachedDecision:
    """A decision no shared budget governs: unbounded, never fatal."""
    return _CachedDecision(time.monotonic(), decision, None, None)


def invalidate_spend_decisions(context: UserContext | None = None) -> None:
    """Force the next ``open`` to re-derive policy from the database.

    Called when a charge exhausts an allowance: the cached decision said this
    user could spend, and it is now wrong, so waiting out the TTL would let the
    rest of a fan-out through on a budget that is already gone.
    """
    active = context or current_context()
    if active is not None:
        active.spend_decisions.clear()


def _settings_provider_key(settings: Settings, provider: str) -> str:
    return {
        "anthropic": settings.anthropic_api_key,
        "openai": settings.openai_api_key,
        "gemini": settings.gemini_api_key,
        "deepseek": settings.deepseek_api_key,
    }.get(provider, "")


def _subscription_decision(
    provider: str, model: str, settings: Settings
) -> SpendDecision | None:
    """The gateway decision for ``provider``, or ``None`` to use its API.

    Checked ahead of every key source because a subscription is not a *cheaper*
    key, it is a different endpoint: once a provider is on the gateway, the
    platform and per-user API keys are not merely lower priority, they are
    wrong -- sending an ``sk-ant-`` key to sub2api authenticates nothing.

    ``own_key=True`` marks the call non-billable. Subscription traffic is
    flat-rate, so metering it against a shared cost quota would throttle calls
    that have no marginal cost. The trade-off is that usage reports attribute
    no spend to these calls; that is accurate, not a gap.
    """
    from resume_agent.llm_routing import (
        effective_mode,
        gateway_base_url,
        subscription_key,
    )

    if effective_mode(provider, settings) != "subscription":
        return None
    return SpendDecision(
        api_key=subscription_key(provider, settings),
        own_key=True,
        provider=provider,
        model=model,
        reason="subscription",
        base_url=gateway_base_url(provider, settings),
    )


@dataclass(frozen=True)
class _SharedVerdict:
    """Whether shared funding is available, and how much of it is left.

    The headroom is what makes the cached decision *exact* rather than merely
    time-bounded. A TTL alone says "this was true 12 seconds ago"; headroom
    says "and it stays true for another N units of spend". Recording usage
    decrements it, so the call that actually exhausts a budget is the call that
    invalidates the decision — no fan-out overshoots a budget just because it
    started inside the window.
    """

    denial: RuntimeError | None
    headroom: float | None  # None = unbounded
    unit: str  # "weighted" (shadow) or "micros" (enforce)


def _evaluate_shared(
    context: UserContext,
    provider: str,
    model: str,
    *,
    now: datetime | None,
) -> _SharedVerdict:
    """Derive shared-funding eligibility, its error, and its headroom at once.

    One evaluation produces the boolean ``shared_key_available`` returns and
    the typed error ``enforce_agent_budget`` raises. Deriving them separately
    is what made the pair cost twice; deriving them together is what makes the
    pair honest, because they can no longer disagree.
    """
    engine = context.system_engine
    enforcing = context.settings.cost_quota_enforcement == "enforce"
    unit = "micros" if enforcing else "weighted"
    if engine is None:
        return _SharedVerdict(None, None, unit)

    with Session(engine) as session:
        user = session.get(User, context.user_id)
        if user is not None and not user.shared_key_access:
            return _SharedVerdict(
                BudgetExceededError(
                    "shared platform models are disabled for this account; "
                    "add your own API key"
                ),
                0.0,
                unit,
            )
        override = user.weekly_token_budget if user is not None else None

    bounds: list[float] = []
    if enforcing:
        if not model or not has_active_rate(engine, provider, model, now=now):
            return _SharedVerdict(
                CostRateUnavailableError(
                    f"no active cost rate for "
                    f"{provider or 'unknown'}:{model or 'unknown'}"
                ),
                0.0,
                unit,
            )
        if not context.is_admin:
            try:
                snapshot = charge_shared_cost(
                    engine, context.user_id, 0, now=now, preflight=True
                )
            except CostQuotaExceededError as exc:
                return _SharedVerdict(exc, 0.0, unit)
            if snapshot.remaining_micros is not None:
                bounds.append(float(snapshot.remaining_micros))
        global_budget = (
            context.settings.global_monthly_cost_quota_micros
            or DEFAULT_GLOBAL_MONTHLY_COST_QUOTA_MICROS
        )
        if global_budget:
            spent = global_monthly_cost(engine, now=now)
            if spent >= global_budget:
                return _SharedVerdict(
                    GlobalCostQuotaExceededError(
                        "platform monthly cost quota is exhausted"
                    ),
                    0.0,
                    unit,
                )
            bounds.append(float(global_budget - spent))
        return _SharedVerdict(None, min(bounds) if bounds else None, unit)

    # Stage-one compatibility: the weighted-token guard remains the active gate
    # while calls dual-record exact cost.
    if not context.is_admin:
        budget = resolve_limit(
            override,
            system_default(engine, "weekly_token_budget", DEFAULT_WEEKLY_TOKEN_BUDGET),
        )
        if budget:
            spent = weekly_usage(engine, context.user_id, now=now)
            if spent >= budget:
                return _SharedVerdict(
                    BudgetExceededError(
                        f"weekly token budget exhausted "
                        f"({spent:,.0f} of {budget:,} weighted tokens)"
                    ),
                    0.0,
                    unit,
                )
            bounds.append(budget - spent)
    global_budget = context.settings.global_weekly_token_budget
    if global_budget:
        spent = global_weekly_usage(engine, now=now)
        if spent >= global_budget:
            return _SharedVerdict(
                BudgetExceededError("platform weekly token budget is exhausted"),
                0.0,
                unit,
            )
        bounds.append(global_budget - spent)
    return _SharedVerdict(None, min(bounds) if bounds else None, unit)


def _shared_denial(
    context: UserContext,
    provider: str,
    model: str,
    *,
    now: datetime | None,
) -> RuntimeError | None:
    """Why a shared key may not fund this call, or ``None`` if it may."""
    return _evaluate_shared(context, provider, model, now=now).denial


class SpendGate:
    """Resolve key selection plus budget for a phase, and settle its usage.

    Two callers, one derivation. ``select`` answers "which key?" and never
    raises; ``open`` answers "may I spend?" and raises. They used to be
    separate code paths that each paid for a full policy evaluation and could
    silently disagree; now the disagreement is impossible because the same
    evaluation produces both.
    """

    def __init__(self, *, settings: Settings | None = None) -> None:
        self._settings = settings

    # -- resolution ---------------------------------------------------------

    def select(self, model_id: str, *, now: datetime | None = None) -> SpendDecision:
        """Return the key this call would use. Never raises on budget."""
        return self._resolve(model_id, now=now)[0]

    def open(self, model_id: str, *, now: datetime | None = None) -> SpendDecision:
        """Return the funded key for ``model_id``, raising if nothing funds it.

        Cached on the active context for ``Settings.spend_gate_ttl_seconds``.
        An explicit ``now`` bypasses the cache: it means a caller is asking
        about a different moment, and a decision made for one moment must not
        answer for another.
        """
        decision, fatal = self._resolve(model_id, now=now)
        if fatal is not None:
            raise fatal
        return decision

    def _resolve(
        self, model_id: str, *, now: datetime | None
    ) -> tuple[SpendDecision, RuntimeError | None]:
        from resume_agent.llm_runner import split_provider

        provider, model = split_provider(model_id)
        context = current_context()
        if context is None:
            settings = self._settings or _current_settings()
            routed = _subscription_decision(provider, model, settings)
            if routed is not None:
                return routed, None
            return (
                SpendDecision(
                    api_key=_settings_provider_key(settings, provider),
                    own_key=False,
                    provider=provider,
                    model=model,
                    reason="settings-key",
                ),
                None,
            )

        cacheable = now is None
        entry = self._cached(context, model_id) if cacheable else None
        if entry is None:
            entry = self._derive(context, provider, model, now=now)
            if cacheable:
                context.spend_decisions[model_id] = entry
        # record_call reads this to decide whether a call is billable, so it
        # must be written on a cache hit too, not only when policy is derived.
        context.selected_own_key_providers[provider] = entry.decision.own_key
        return entry.decision, entry.fatal

    def _cached(self, context: UserContext, model_id: str) -> _CachedDecision | None:
        entry = context.spend_decisions.get(model_id)
        if not isinstance(entry, _CachedDecision):
            return None
        ttl = context.settings.spend_gate_ttl_seconds
        if ttl <= 0 or time.monotonic() - entry.stamped >= ttl:
            context.spend_decisions.pop(model_id, None)
            return None
        return entry

    def _derive(
        self,
        context: UserContext,
        provider: str,
        model: str,
        *,
        now: datetime | None,
    ) -> _CachedDecision:
        # Ahead of every key source: a routed provider has a different
        # endpoint, so no API key -- platform, user, or settings -- is the
        # right credential for it.
        routed = _subscription_decision(
            provider, model, self._settings or context.settings
        )
        if routed is not None:
            return _settled(routed)

        platform_key = context.platform_provider_keys.get(provider, "")
        user_key = context.user_provider_keys.get(provider, "")

        if not platform_key:
            if user_key:
                # Bring-your-own-key: no shared budget applies, so no query.
                return _settled(SpendDecision(user_key, True, provider, model, "byok"))
            settings = self._settings or context.settings
            key = _settings_provider_key(settings, provider)
            if provider in context.own_key_providers:
                return _settled(SpendDecision(key, True, provider, model, "own-key"))
            # No own key. Budget still governs the call even with no platform
            # key configured — enforce_agent_budget never had a platform-key
            # precondition, only shared_key_available did, and conflating the
            # two here would silently un-gate every deployment that funds
            # models from Settings rather than from platform_provider_keys.
            verdict = _evaluate_shared(context, provider, model, now=now)
            return _CachedDecision(
                time.monotonic(),
                SpendDecision(key, False, provider, model, "settings-key"),
                verdict.denial,
                verdict.headroom,
                verdict.unit,
            )

        verdict = _evaluate_shared(context, provider, model, now=now)
        if verdict.denial is None:
            return _CachedDecision(
                time.monotonic(),
                SpendDecision(platform_key, False, provider, model, "shared"),
                None,
                verdict.headroom,
                verdict.unit,
            )
        if user_key:
            # Shared funding is gone but the user has their own key, so the
            # call proceeds on it and nothing is raised — what resolve_api_key
            # has always done.
            return _settled(
                SpendDecision(user_key, True, provider, model, "own-key-fallback")
            )
        # Nothing funds this call. The platform key is still reported so a
        # non-raising caller behaves exactly as before; the error is what the
        # enforcing caller gets.
        return _CachedDecision(
            time.monotonic(),
            SpendDecision(platform_key, False, provider, model, "unfunded"),
            verdict.denial,
            0.0,
            verdict.unit,
        )

    # -- settlement ---------------------------------------------------------

    def settle(
        self,
        snapshot: QuotaSnapshot | None = None,
        *,
        weighted: float = 0.0,
        cost_micros: int = 0,
    ) -> None:
        """Charge a completed call against every cached decision's headroom.

        A decision is dropped the moment its headroom runs out, so the call
        that exhausts a budget is the call that invalidates the cache — the TTL
        is a ceiling on staleness, not the mechanism that keeps it correct.
        """
        context = current_context()
        if context is None:
            return
        if snapshot is not None:
            remaining = snapshot.remaining_micros
            if remaining is not None and remaining <= 0:
                context.spend_decisions.clear()
                return
        for model_id, entry in list(context.spend_decisions.items()):
            if not isinstance(entry, _CachedDecision) or entry.headroom is None:
                continue
            entry.headroom -= cost_micros if entry.unit == "micros" else weighted
            if entry.headroom <= 0:
                context.spend_decisions.pop(model_id, None)


def _current_settings() -> Settings:
    from resume_agent.config import get_settings

    return get_settings()
