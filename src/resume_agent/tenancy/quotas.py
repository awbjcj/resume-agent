from __future__ import annotations

import calendar
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from resume_agent.tenancy.system_db import (
    QuotaAccount,
    QuotaLedgerEntry,
    QuotaOperation,
    QuotaOperationPreview,
    QuotaPeriod,
    QuotaTier,
    UsageEvent,
    User,
)

FREE_ALLOWANCE_MICROS = 1_000_000
SUBSCRIBER_ALLOWANCE_MICROS = 20_000_000
DEFAULT_GLOBAL_MONTHLY_COST_QUOTA_MICROS = 500_000_000


class CostQuotaExceededError(RuntimeError):
    code = "COST_QUOTA_EXCEEDED"


class GlobalCostQuotaExceededError(RuntimeError):
    code = "GLOBAL_COST_QUOTA_EXCEEDED"


class StaleQuotaPreviewError(RuntimeError):
    code = "QUOTA_PREVIEW_STALE"


class InsufficientCreditError(RuntimeError):
    code = "INSUFFICIENT_CREDIT"


class IdempotencyConflictError(RuntimeError):
    code = "IDEMPOTENCY_CONFLICT"


@dataclass(frozen=True)
class QuotaSnapshot:
    user_id: str
    tier_id: str
    tier_name: str
    period_start: datetime
    period_end: datetime
    allowance_micros: int | None
    override_micros: int | None
    spent_micros: int
    credit_balance_micros: int
    credit_spent_micros: int
    overage_micros: int
    remaining_micros: int | None
    is_unlimited: bool


def seed_quota_tiers(engine: Engine) -> None:
    with Session(engine) as session:
        if session.get(QuotaTier, "FREE") is None:
            session.add(
                QuotaTier(
                    id="FREE",
                    name="Free",
                    cycle_unit="WEEK",
                    cycle_count=1,
                    allowance_micros=FREE_ALLOWANCE_MICROS,
                    is_default=True,
                )
            )
        if session.get(QuotaTier, "SUBSCRIBER") is None:
            session.add(
                QuotaTier(
                    id="SUBSCRIBER",
                    name="Subscriber",
                    cycle_unit="MONTH",
                    cycle_count=1,
                    allowance_micros=SUBSCRIBER_ALLOWANCE_MICROS,
                )
            )
        session.commit()


def seed_quota_accounts(engine: Engine) -> None:
    """Assign every existing non-admin account to FREE during migration."""

    with Session(engine) as session:
        user_ids = list(
            session.execute(select(User.id).where(User.role != "admin")).scalars()
        )
    for user_id in user_ids:
        ensure_quota_account(engine, user_id)


def assign_new_member(
    session: Session, user_id: str, *, now: datetime | None = None
) -> None:
    """Create the FREE account and anchored first period in a signup transaction."""

    _ensure_in_session(session, user_id, now or datetime.now(timezone.utc))


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _add_months(anchor: datetime, months: int) -> datetime:
    zero_based = anchor.month - 1 + months
    year = anchor.year + zero_based // 12
    month = zero_based % 12 + 1
    day = min(anchor.day, calendar.monthrange(year, month)[1])
    return anchor.replace(year=year, month=month, day=day)


def _period_end(
    start: datetime, tier: QuotaTier, *, anchor: datetime | None = None
) -> datetime:
    if tier.cycle_unit == "WEEK":
        return start + timedelta(weeks=tier.cycle_count)
    if tier.cycle_unit == "MONTH":
        cycle_anchor = anchor or start
        months = tier.cycle_count
        candidate = _add_months(cycle_anchor, months)
        while candidate <= start:
            months += tier.cycle_count
            candidate = _add_months(cycle_anchor, months)
        return candidate
    raise ValueError(f"unsupported quota cycle {tier.cycle_unit!r}")


def _allowance(account: QuotaAccount, tier: QuotaTier) -> int | None:
    return (
        account.quota_override_micros
        if account.quota_override_micros is not None
        else tier.allowance_micros
    )


def _new_period(
    session: Session,
    account: QuotaAccount,
    tier: QuotaTier,
    start: datetime,
) -> QuotaPeriod:
    period = QuotaPeriod(
        id=uuid.uuid4().hex,
        user_id=account.user_id,
        tier_id=tier.id,
        starts_at=start,
        ends_at=_period_end(start, tier, anchor=_aware(account.anchor_at)),
        allowance_micros=_allowance(account, tier),
    )
    session.add(period)
    session.flush()
    account.active_period_id = period.id
    return period


def _ensure_in_session(
    session: Session, user_id: str, now: datetime
) -> tuple[QuotaAccount, QuotaPeriod, QuotaTier]:
    account = session.get(QuotaAccount, user_id)
    if account is None:
        account = QuotaAccount(user_id=user_id, tier_id="FREE", anchor_at=now)
        session.add(account)
        session.flush()
    tier = session.get(QuotaTier, account.tier_id)
    if tier is None:
        raise RuntimeError(f"quota tier {account.tier_id!r} does not exist")
    period = (
        session.get(QuotaPeriod, account.active_period_id)
        if account.active_period_id
        else None
    )
    if period is None:
        account.anchor_at = now
        period = _new_period(session, account, tier, now)
    while now >= _aware(period.ends_at):
        period.closed_at = period.ends_at
        next_start = _aware(period.ends_at)
        period = _new_period(session, account, tier, next_start)
    return account, period, tier


def _snapshot(
    account: QuotaAccount, period: QuotaPeriod, tier: QuotaTier
) -> QuotaSnapshot:
    unlimited = period.allowance_micros is None
    recurring_remaining = (
        None if unlimited else max(0, period.allowance_micros - period.spent_micros)
    )
    remaining = (
        None
        if recurring_remaining is None
        else recurring_remaining + account.credit_balance_micros
    )
    return QuotaSnapshot(
        user_id=account.user_id,
        tier_id=tier.id,
        tier_name=tier.name,
        period_start=_aware(period.starts_at),
        period_end=_aware(period.ends_at),
        allowance_micros=period.allowance_micros,
        override_micros=account.quota_override_micros,
        spent_micros=period.spent_micros,
        credit_balance_micros=account.credit_balance_micros,
        credit_spent_micros=period.credit_spent_micros,
        overage_micros=period.overage_micros,
        remaining_micros=remaining,
        is_unlimited=unlimited,
    )


def ensure_quota_account(
    engine: Engine, user_id: str, *, now: datetime | None = None
) -> QuotaSnapshot:
    moment = now or datetime.now(timezone.utc)
    with Session(engine) as session:
        session.execute(text("BEGIN IMMEDIATE"))
        account, period, tier = _ensure_in_session(session, user_id, moment)
        session.commit()
        return _snapshot(account, period, tier)


def quota_snapshot(
    engine: Engine, user_id: str, *, now: datetime | None = None
) -> QuotaSnapshot:
    return ensure_quota_account(engine, user_id, now=now)


def charge_shared_cost(
    engine: Engine,
    user_id: str,
    amount_micros: int,
    *,
    now: datetime | None = None,
    preflight: bool = False,
    usage_event_id: int | None = None,
) -> QuotaSnapshot:
    moment = now or datetime.now(timezone.utc)
    with Session(engine) as session:
        session.execute(text("BEGIN IMMEDIATE"))
        account, period, tier = _ensure_in_session(session, user_id, moment)
        before = _snapshot(account, period, tier)
        if preflight:
            if before.remaining_micros is not None and before.remaining_micros <= 0:
                raise CostQuotaExceededError(
                    f"cost quota exhausted; resets at {before.period_end.isoformat()}"
                )
            session.commit()
            return before
        if amount_micros < 0:
            raise ValueError("cost cannot be negative")
        allowance = period.allowance_micros
        recurring_remaining = (
            amount_micros
            if allowance is None
            else max(0, allowance - period.spent_micros)
        )
        recurring = min(amount_micros, recurring_remaining)
        after_recurring = amount_micros - recurring
        credit = min(after_recurring, account.credit_balance_micros)
        overage = after_recurring - credit
        period.spent_micros += amount_micros
        period.credit_spent_micros += credit
        period.overage_micros += overage
        account.credit_balance_micros -= credit
        session.add(
            QuotaLedgerEntry(
                user_id=user_id,
                period_id=period.id,
                usage_event_id=usage_event_id,
                kind="USAGE",
                amount_micros=-amount_micros,
                recurring_micros=recurring,
                credit_micros=credit,
                overage_micros=overage,
            )
        )
        session.commit()
        return _snapshot(account, period, tier)


def grant_credit(
    engine: Engine, user_id: str, amount_micros: int, *, now: datetime | None = None
) -> QuotaSnapshot:
    if amount_micros <= 0:
        raise ValueError("credit must be positive")
    moment = now or datetime.now(timezone.utc)
    with Session(engine) as session:
        account, period, tier = _ensure_in_session(session, user_id, moment)
        account.credit_balance_micros += amount_micros
        session.add(
            QuotaLedgerEntry(
                user_id=user_id,
                period_id=period.id,
                kind="CREDIT_GRANT",
                amount_micros=amount_micros,
                credit_micros=amount_micros,
            )
        )
        session.commit()
        return _snapshot(account, period, tier)


def debit_credit(
    engine: Engine, user_id: str, amount_micros: int, *, now: datetime | None = None
) -> QuotaSnapshot:
    if amount_micros <= 0:
        raise ValueError("debit must be positive")
    moment = now or datetime.now(timezone.utc)
    with Session(engine) as session:
        account, period, tier = _ensure_in_session(session, user_id, moment)
        if account.credit_balance_micros < amount_micros:
            raise InsufficientCreditError("insufficient credit balance")
        account.credit_balance_micros -= amount_micros
        session.add(
            QuotaLedgerEntry(
                user_id=user_id,
                period_id=period.id,
                kind="CREDIT_DEBIT",
                amount_micros=-amount_micros,
                credit_micros=amount_micros,
            )
        )
        session.commit()
        return _snapshot(account, period, tier)


def reset_current_period(
    engine: Engine, user_id: str, *, now: datetime | None = None
) -> QuotaSnapshot:
    moment = now or datetime.now(timezone.utc)
    with Session(engine) as session:
        account, period, tier = _ensure_in_session(session, user_id, moment)
        refunded = period.credit_spent_micros
        forgiven = period.spent_micros
        account.credit_balance_micros += refunded
        period.spent_micros = 0
        period.credit_spent_micros = 0
        period.overage_micros = 0
        session.add(
            QuotaLedgerEntry(
                user_id=user_id,
                period_id=period.id,
                kind="RESET",
                amount_micros=forgiven,
                credit_micros=refunded,
            )
        )
        session.commit()
        return _snapshot(account, period, tier)


def change_tier(
    engine: Engine,
    user_id: str,
    tier_id: str,
    *,
    now: datetime | None = None,
    actor_user_id: str | None = None,
    reason: str | None = None,
) -> QuotaSnapshot:
    moment = now or datetime.now(timezone.utc)
    with Session(engine) as session:
        account, period, _old_tier = _ensure_in_session(session, user_id, moment)
        tier = session.get(QuotaTier, tier_id)
        if tier is None or tier.archived_at is not None:
            raise ValueError("quota tier is unavailable")
        period.closed_at = moment
        previous_tier_id = account.tier_id
        account.tier_id = tier.id
        account.anchor_at = moment
        new_period = _new_period(session, account, tier, moment)
        session.add(
            QuotaLedgerEntry(
                user_id=user_id,
                period_id=new_period.id,
                kind="TIER_CHANGE",
                amount_micros=0,
                actor_user_id=actor_user_id,
                reason=reason,
                snapshot_json=json.dumps(
                    {
                        "before": {"tierId": previous_tier_id},
                        "after": {"tierId": tier.id},
                    }
                ),
            )
        )
        session.commit()
        return _snapshot(account, new_period, tier)


def global_monthly_cost(engine: Engine, *, now: datetime | None = None) -> int:
    moment = now or datetime.now(timezone.utc)
    start = datetime(moment.year, moment.month, 1, tzinfo=timezone.utc)
    with Session(engine) as session:
        return int(
            session.execute(
                select(func.coalesce(func.sum(UsageEvent.cost_micros), 0)).where(
                    UsageEvent.own_key.is_(False),
                    UsageEvent.ts >= start,
                    UsageEvent.cost_micros.is_not(None),
                )
            ).scalar_one()
        )


def create_operation_preview(
    engine: Engine,
    *,
    actor_user_id: str,
    target_type: str,
    target_value: str | None,
    action_type: str,
    amount_micros: int | None,
    now: datetime | None = None,
) -> QuotaOperationPreview:
    moment = now or datetime.now(timezone.utc)
    if target_type not in {"USER", "TIER", "ALL_MEMBERS"}:
        raise ValueError("invalid quota target")
    if action_type not in {"RESET_CURRENT_PERIOD", "GRANT_CREDIT", "DEBIT_CREDIT"}:
        raise ValueError("invalid quota operation")
    if action_type != "RESET_CURRENT_PERIOD" and (
        amount_micros is None or amount_micros <= 0
    ):
        raise ValueError("credit operations require a positive amount")
    with Session(engine) as session:
        query = select(User.id).where(User.role != "admin")
        if target_type == "USER":
            query = query.where(User.id == target_value)
        elif target_type == "TIER":
            query = query.join(QuotaAccount, QuotaAccount.user_id == User.id).where(
                QuotaAccount.tier_id == target_value
            )
        user_ids = list(session.execute(query.order_by(User.id)).scalars())
        if target_type == "USER" and not user_ids:
            raise ValueError("target user is not a member")
        preview = QuotaOperationPreview(
            id=uuid.uuid4().hex,
            created_by=actor_user_id,
            target_type=target_type,
            target_value=target_value,
            action_type=action_type,
            amount_micros=amount_micros,
            target_user_ids=json.dumps(user_ids),
            expires_at=moment + timedelta(minutes=15),
        )
        session.add(preview)
        session.commit()
        session.refresh(preview)
        return preview


def execute_operation(
    engine: Engine,
    *,
    preview_id: str,
    actor_user_id: str,
    reason: str,
    idempotency_key: str,
    now: datetime | None = None,
) -> QuotaOperation:
    moment = now or datetime.now(timezone.utc)
    if not reason.strip():
        raise ValueError("reason is required")
    with Session(engine, expire_on_commit=False) as session:
        session.execute(text("BEGIN IMMEDIATE"))
        existing = session.execute(
            select(QuotaOperation).where(
                QuotaOperation.idempotency_key == idempotency_key
            )
        ).scalar_one_or_none()
        if existing is not None:
            if (
                existing.preview_id != preview_id
                or existing.actor_user_id != actor_user_id
            ):
                raise IdempotencyConflictError(
                    "idempotency key was already used for another quota operation"
                )
            return existing
        preview = session.get(QuotaOperationPreview, preview_id)
        if (
            preview is None
            or preview.created_by != actor_user_id
            or preview.used_at is not None
            or _aware(preview.expires_at) <= moment
        ):
            raise StaleQuotaPreviewError("quota operation preview is stale")
        user_ids: list[str] = json.loads(preview.target_user_ids)
        operation = QuotaOperation(
            id=uuid.uuid4().hex,
            idempotency_key=idempotency_key,
            preview_id=preview.id,
            actor_user_id=actor_user_id,
            action_type=preview.action_type,
            target_type=preview.target_type,
            target_value=preview.target_value,
            amount_micros=preview.amount_micros,
            reason=reason.strip(),
            affected_count=len(user_ids),
        )
        session.add(operation)
        session.flush()
        for user_id in user_ids:
            account, period, _tier = _ensure_in_session(session, user_id, moment)
            before = {
                "spentMicros": period.spent_micros,
                "creditBalanceMicros": account.credit_balance_micros,
                "creditSpentMicros": period.credit_spent_micros,
                "overageMicros": period.overage_micros,
            }
            amount = preview.amount_micros or 0
            if preview.action_type == "RESET_CURRENT_PERIOD":
                credit_amount = period.credit_spent_micros
                ledger_amount = period.spent_micros
                account.credit_balance_micros += credit_amount
                period.spent_micros = 0
                period.credit_spent_micros = 0
                period.overage_micros = 0
                kind = "RESET"
            elif preview.action_type == "GRANT_CREDIT":
                account.credit_balance_micros += amount
                credit_amount = amount
                ledger_amount = amount
                kind = "CREDIT_GRANT"
            else:
                if account.credit_balance_micros < amount:
                    raise InsufficientCreditError(
                        f"user {user_id} has insufficient credit"
                    )
                account.credit_balance_micros -= amount
                credit_amount = amount
                ledger_amount = -amount
                kind = "CREDIT_DEBIT"
            after = {
                "spentMicros": period.spent_micros,
                "creditBalanceMicros": account.credit_balance_micros,
                "creditSpentMicros": period.credit_spent_micros,
                "overageMicros": period.overage_micros,
            }
            session.add(
                QuotaLedgerEntry(
                    user_id=user_id,
                    period_id=period.id,
                    operation_id=operation.id,
                    kind=kind,
                    amount_micros=ledger_amount,
                    credit_micros=credit_amount,
                    actor_user_id=actor_user_id,
                    reason=reason.strip(),
                    snapshot_json=json.dumps({"before": before, "after": after}),
                )
            )
        preview.used_at = moment
        session.commit()
        return operation
