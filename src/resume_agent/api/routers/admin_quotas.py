from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, or_, select, true
from sqlalchemy.orm import Session

from resume_agent.api.deps import require_admin
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.admin_quotas import (
    LlmRateCreate,
    LlmRateOut,
    LlmRatePage,
    QuotaAccountOut,
    QuotaAccountPage,
    QuotaAccountPatch,
    QuotaOperationCommit,
    QuotaOperationOut,
    QuotaOperationPage,
    QuotaOperationPreviewCreate,
    QuotaOperationPreviewOut,
    QuotaPlatformSummary,
    QuotaLedgerEntryOut,
    QuotaLedgerPage,
    QuotaTierCreate,
    QuotaTierOut,
    QuotaTierPage,
    QuotaTierPatch,
)
from resume_agent.api.schemas.base import Pagination
from resume_agent.tenancy.context import UserContext
from resume_agent.tenancy.costs import invalidate_rate_cache, normalize_provider
from resume_agent.tenancy.quotas import (
    InsufficientCreditError,
    IdempotencyConflictError,
    StaleQuotaPreviewError,
    change_tier,
    create_operation_preview,
    ensure_quota_account,
    execute_operation,
)
from resume_agent.tenancy.system_db import (
    LlmRate,
    QuotaAccount,
    QuotaLedgerEntry,
    QuotaOperation,
    QuotaPeriod,
    QuotaTier,
    UsageEvent,
    User,
)

router = APIRouter(prefix="/admin", tags=["admin-quotas"])


@router.get("/quota-summary")
def quota_summary(
    request: Request,
    _context: UserContext = Depends(require_admin),
) -> QuotaPlatformSummary:
    now = datetime.now(timezone.utc)
    month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    if now.month == 12:
        next_reset = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        next_reset = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
    with Session(request.app.state.system_engine) as session:
        spend, unpriced = session.execute(
            select(
                func.coalesce(func.sum(UsageEvent.quota_cost_micros), 0),
                func.coalesce(
                    func.sum(func.iif(UsageEvent.pricing_status != "PRICED", 1, 0)), 0
                ),
            ).where(UsageEvent.ts >= month_start, UsageEvent.own_key.is_(False))
        ).one()
    cap = request.app.state.settings.global_monthly_cost_quota_micros
    return QuotaPlatformSummary(
        monthly_spend_micros=int(spend),
        monthly_cap_micros=cap,
        remaining_micros=max(0, cap - int(spend)),
        unpriced_call_count=int(unpriced),
        next_reset_at=next_reset,
    )


def _pagination(page: int, page_size: int, total: int) -> Pagination:
    return Pagination(
        page=page,
        page_size=page_size,
        total_items=total,
        total_pages=(total + page_size - 1) // page_size,
    )


def _tier_out(session: Session, tier: QuotaTier) -> QuotaTierOut:
    member_count = session.execute(
        select(func.count())
        .select_from(QuotaAccount)
        .where(QuotaAccount.tier_id == tier.id)
    ).scalar_one()
    spend = session.execute(
        select(func.coalesce(func.sum(QuotaPeriod.spent_micros), 0)).where(
            QuotaPeriod.tier_id == tier.id, QuotaPeriod.closed_at.is_(None)
        )
    ).scalar_one()
    return QuotaTierOut.model_validate(tier).model_copy(
        update={"member_count": int(member_count), "spend_micros": int(spend)}
    )


@router.get("/quota-tiers")
def list_tiers(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    include_archived: bool = False,
    _context: UserContext = Depends(require_admin),
) -> QuotaTierPage:
    with Session(request.app.state.system_engine) as session:
        query = select(QuotaTier)
        if not include_archived:
            query = query.where(QuotaTier.archived_at.is_(None))
        total = int(
            session.execute(
                select(func.count()).select_from(query.subquery())
            ).scalar_one()
        )
        rows = (
            session.execute(
                query.order_by(QuotaTier.is_default.desc(), QuotaTier.name)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            .scalars()
            .all()
        )
        return QuotaTierPage(
            data=[_tier_out(session, row) for row in rows],
            pagination=_pagination(page, page_size, total),
        )


@router.post("/quota-tiers", status_code=201)
def create_tier(
    body: QuotaTierCreate,
    request: Request,
    _context: UserContext = Depends(require_admin),
) -> QuotaTierOut:
    with Session(request.app.state.system_engine) as session:
        if session.get(QuotaTier, body.id) is not None:
            raise ApiException(409, "TIER_EXISTS", "Quota tier already exists")
        tier = QuotaTier(**body.model_dump(exclude={"reason"}))
        session.add(tier)
        session.commit()
        session.refresh(tier)
        return _tier_out(session, tier)


@router.get("/quota-tiers/{tier_id}")
def get_tier(
    tier_id: str,
    request: Request,
    _context: UserContext = Depends(require_admin),
) -> QuotaTierOut:
    with Session(request.app.state.system_engine) as session:
        tier = session.get(QuotaTier, tier_id)
        if tier is None:
            raise ApiException(404, "NOT_FOUND", "No such quota tier")
        return _tier_out(session, tier)


@router.patch("/quota-tiers/{tier_id}")
def patch_tier(
    tier_id: str,
    body: QuotaTierPatch,
    request: Request,
    context: UserContext = Depends(require_admin),
) -> QuotaTierOut:
    with Session(request.app.state.system_engine) as session:
        tier = session.get(QuotaTier, tier_id)
        if tier is None:
            raise ApiException(404, "NOT_FOUND", "No such quota tier")
        if body.archived and tier.is_default:
            raise ApiException(
                409, "DEFAULT_TIER_REQUIRED", "The FREE tier cannot be archived"
            )
        for field in ("name", "cycle_unit", "cycle_count", "allowance_micros"):
            if field in body.model_fields_set:
                setattr(tier, field, getattr(body, field))
        if body.archived is not None:
            tier.archived_at = datetime.now(timezone.utc) if body.archived else None
        if "allowance_micros" in body.model_fields_set:
            periods = session.execute(
                select(QuotaPeriod)
                .join(QuotaAccount, QuotaAccount.active_period_id == QuotaPeriod.id)
                .where(
                    QuotaAccount.tier_id == tier.id,
                    QuotaAccount.quota_override_micros.is_(None),
                )
            ).scalars()
            for period in periods:
                before_allowance = period.allowance_micros
                period.allowance_micros = tier.allowance_micros
                session.add(
                    QuotaLedgerEntry(
                        user_id=period.user_id,
                        period_id=period.id,
                        kind="TIER_ALLOWANCE_CHANGE",
                        amount_micros=0,
                        actor_user_id=context.user_id,
                        reason=body.reason,
                        snapshot_json=json.dumps(
                            {
                                "before": {"allowanceMicros": before_allowance},
                                "after": {"allowanceMicros": tier.allowance_micros},
                            }
                        ),
                    )
                )
        session.commit()
        session.refresh(tier)
        return _tier_out(session, tier)


def _account_out(session: Session, user: User) -> QuotaAccountOut:
    account = session.get(QuotaAccount, user.id)
    if account is None or account.active_period_id is None:
        raise RuntimeError("quota account was not initialized")
    period = session.get(QuotaPeriod, account.active_period_id)
    if period is None:
        raise RuntimeError("active quota period is missing")
    allowance = period.allowance_micros
    recurring = None if allowance is None else max(0, allowance - period.spent_micros)
    remaining = None if recurring is None else recurring + account.credit_balance_micros
    if allowance is None:
        status = "UNLIMITED"
    elif period.overage_micros:
        status = "OVERAGE"
    elif remaining == 0:
        status = "EXHAUSTED"
    else:
        status = "ACTIVE"
    sums = session.execute(
        select(
            func.coalesce(func.sum(UsageEvent.quota_cost_micros), 0),
            func.coalesce(
                func.sum(UsageEvent.cost_micros).filter(UsageEvent.own_key.is_(True)), 0
            ),
            func.coalesce(func.sum(UsageEvent.total_tokens), 0),
        ).where(UsageEvent.user_id == user.id)
    ).one()
    return QuotaAccountOut(
        user_id=user.id,
        username=user.username,
        disabled=user.disabled_at is not None,
        tier_id=account.tier_id,
        allowance_micros=allowance,
        override_micros=account.quota_override_micros,
        spent_micros=period.spent_micros,
        recurring_remaining_micros=recurring,
        credit_balance_micros=account.credit_balance_micros,
        remaining_micros=remaining,
        overage_micros=period.overage_micros,
        period_start=period.starts_at,
        period_end=period.ends_at,
        status=status,
        shared_cost_micros=int(sums[0]),
        byok_cost_micros=int(sums[1]),
        total_tokens=int(sums[2]),
    )


@router.get("/quota-accounts")
def list_accounts(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    search: str | None = None,
    tier: str | None = None,
    status: str | None = None,
    balance: str | None = None,
    disabled: bool | None = None,
    _context: UserContext = Depends(require_admin),
) -> QuotaAccountPage:
    engine = request.app.state.system_engine
    with Session(engine) as session:
        member_ids = list(
            session.execute(select(User.id).where(User.role != "admin")).scalars()
        )
    for user_id in member_ids:
        ensure_quota_account(engine, user_id)
    with Session(engine) as session:
        query = (
            select(User)
            .join(QuotaAccount, QuotaAccount.user_id == User.id)
            .where(User.role != "admin")
        )
        if search:
            query = query.where(User.username.ilike(f"%{search.strip()}%"))
        if tier:
            query = query.where(QuotaAccount.tier_id == tier)
        if disabled is not None:
            query = query.where(
                User.disabled_at.is_not(None)
                if disabled
                else User.disabled_at.is_(None)
            )
        rows = session.execute(query.order_by(User.username)).scalars().all()
        results = [_account_out(session, row) for row in rows]
        if status:
            results = [row for row in results if row.status == status]
        if balance == "POSITIVE":
            results = [
                row
                for row in results
                if row.remaining_micros is not None and row.remaining_micros > 0
            ]
        elif balance == "ZERO":
            results = [row for row in results if row.remaining_micros == 0]
        elif balance == "OVERAGE":
            results = [row for row in results if row.overage_micros > 0]
        elif balance == "UNLIMITED":
            results = [row for row in results if row.remaining_micros is None]
        total = len(results)
        results = results[(page - 1) * page_size : page * page_size]
        return QuotaAccountPage(
            data=results, pagination=_pagination(page, page_size, total)
        )


@router.get("/quota-accounts/{user_id}")
def get_account(
    user_id: str,
    request: Request,
    _context: UserContext = Depends(require_admin),
) -> QuotaAccountOut:
    with Session(request.app.state.system_engine) as session:
        user = session.get(User, user_id)
        if user is None or user.role == "admin":
            raise ApiException(404, "NOT_FOUND", "No such member")
    ensure_quota_account(request.app.state.system_engine, user_id)
    with Session(request.app.state.system_engine) as session:
        user = session.get(User, user_id)
        assert user is not None
        return _account_out(session, user)


@router.get("/quota-accounts/{user_id}/ledger")
def account_ledger(
    user_id: str,
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    _context: UserContext = Depends(require_admin),
) -> QuotaLedgerPage:
    with Session(request.app.state.system_engine) as session:
        user = session.get(User, user_id)
        if user is None or user.role == "admin":
            raise ApiException(404, "NOT_FOUND", "No such member")
        query = select(QuotaLedgerEntry).where(QuotaLedgerEntry.user_id == user_id)
        total = int(
            session.execute(
                select(func.count()).select_from(query.subquery())
            ).scalar_one()
        )
        rows = (
            session.execute(
                query.order_by(QuotaLedgerEntry.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            .scalars()
            .all()
        )
        return QuotaLedgerPage(
            data=[QuotaLedgerEntryOut.model_validate(row) for row in rows],
            pagination=_pagination(page, page_size, total),
        )


@router.patch("/quota-accounts/{user_id}")
def patch_account(
    user_id: str,
    body: QuotaAccountPatch,
    request: Request,
    context: UserContext = Depends(require_admin),
) -> QuotaAccountOut:
    engine = request.app.state.system_engine
    with Session(engine) as session:
        user = session.get(User, user_id)
        if user is None or user.role == "admin":
            raise ApiException(404, "NOT_FOUND", "No such member")
    ensure_quota_account(engine, user_id)
    if body.tier_id is not None:
        try:
            change_tier(
                engine,
                user_id,
                body.tier_id,
                actor_user_id=context.user_id,
                reason=body.reason,
            )
        except ValueError as exc:
            raise ApiException(409, "TIER_UNAVAILABLE", str(exc)) from exc
    if "allowance_override_micros" in body.model_fields_set:
        with Session(engine) as session:
            account = session.get(QuotaAccount, user_id)
            if account is None:
                raise ApiException(404, "NOT_FOUND", "No such member")
            previous_override = account.quota_override_micros
            account.quota_override_micros = body.allowance_override_micros
            period = session.get(QuotaPeriod, account.active_period_id)
            tier = session.get(QuotaTier, account.tier_id)
            if period is not None and tier is not None:
                period.allowance_micros = (
                    body.allowance_override_micros
                    if body.allowance_override_micros is not None
                    else tier.allowance_micros
                )
                session.add(
                    QuotaLedgerEntry(
                        user_id=user_id,
                        period_id=period.id,
                        kind="OVERRIDE_CHANGE",
                        amount_micros=0,
                        actor_user_id=context.user_id,
                        reason=body.reason,
                        snapshot_json=json.dumps(
                            {
                                "before": {"overrideMicros": previous_override},
                                "after": {
                                    "overrideMicros": body.allowance_override_micros
                                },
                            }
                        ),
                    )
                )
            session.commit()
    return get_account(user_id, request, context)


@router.post("/quota-operation-previews", status_code=201)
def preview_operation(
    body: QuotaOperationPreviewCreate,
    request: Request,
    context: UserContext = Depends(require_admin),
) -> QuotaOperationPreviewOut:
    try:
        preview = create_operation_preview(
            request.app.state.system_engine,
            actor_user_id=context.user_id,
            **body.model_dump(),
        )
    except ValueError as exc:
        raise ApiException(422, "INVALID_QUOTA_OPERATION", str(exc)) from exc
    count = len(json.loads(preview.target_user_ids))
    return QuotaOperationPreviewOut(
        id=preview.id,
        target_type=preview.target_type,
        target_value=preview.target_value,
        action_type=preview.action_type,
        amount_micros=preview.amount_micros,
        affected_count=count,
        total_effect_micros=count * (preview.amount_micros or 0),
        expires_at=preview.expires_at,
    )


@router.post("/quota-operations", status_code=201)
def commit_operation(
    body: QuotaOperationCommit,
    request: Request,
    context: UserContext = Depends(require_admin),
) -> QuotaOperationOut:
    try:
        operation = execute_operation(
            request.app.state.system_engine,
            actor_user_id=context.user_id,
            **body.model_dump(),
        )
    except StaleQuotaPreviewError as exc:
        raise ApiException(409, exc.code, str(exc)) from exc
    except InsufficientCreditError as exc:
        raise ApiException(409, exc.code, str(exc)) from exc
    except IdempotencyConflictError as exc:
        raise ApiException(409, exc.code, str(exc)) from exc
    return QuotaOperationOut.model_validate(operation)


@router.get("/quota-operations")
def list_operations(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    _context: UserContext = Depends(require_admin),
) -> QuotaOperationPage:
    with Session(request.app.state.system_engine) as session:
        total = int(
            session.execute(
                select(func.count()).select_from(QuotaOperation)
            ).scalar_one()
        )
        rows = (
            session.execute(
                select(QuotaOperation)
                .order_by(QuotaOperation.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            .scalars()
            .all()
        )
        return QuotaOperationPage(
            data=[QuotaOperationOut.model_validate(row) for row in rows],
            pagination=_pagination(page, page_size, total),
        )


@router.get("/llm-rates")
def list_rates(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=100),
    _context: UserContext = Depends(require_admin),
) -> LlmRatePage:
    with Session(request.app.state.system_engine) as session:
        total = int(
            session.execute(select(func.count()).select_from(LlmRate)).scalar_one()
        )
        rows = (
            session.execute(
                select(LlmRate)
                .order_by(
                    LlmRate.provider, LlmRate.model, LlmRate.effective_from.desc()
                )
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
            .scalars()
            .all()
        )
        return LlmRatePage(
            data=[LlmRateOut.model_validate(row) for row in rows],
            pagination=_pagination(page, page_size, total),
        )


@router.post("/llm-rates", status_code=201)
def create_rate(
    body: LlmRateCreate,
    request: Request,
    context: UserContext = Depends(require_admin),
) -> LlmRateOut:
    values = body.model_dump(exclude={"reason"})
    values["provider"] = normalize_provider(body.provider)
    if (
        body.context_max_tokens is not None
        and body.context_max_tokens < body.context_min_tokens
    ):
        raise ApiException(
            422, "INVALID_CONTEXT_BAND", "Context maximum is below minimum"
        )
    with Session(request.app.state.system_engine) as session:
        context_max_clause = (
            LlmRate.context_max_tokens.is_(None)
            if body.context_max_tokens is None
            else LlmRate.context_max_tokens == body.context_max_tokens
        )
        predecessor = (
            session.execute(
                select(LlmRate)
                .where(
                    LlmRate.provider == values["provider"],
                    LlmRate.model == body.model,
                    LlmRate.context_min_tokens == body.context_min_tokens,
                    context_max_clause,
                    LlmRate.effective_to.is_(None),
                    LlmRate.effective_from < body.effective_from,
                )
                .order_by(LlmRate.effective_from.desc())
            )
            .scalars()
            .first()
        )
        if predecessor is not None:
            predecessor.effective_to = body.effective_from
            session.flush()
        incoming_context_end_clause = (
            true()
            if body.context_max_tokens is None
            else LlmRate.context_min_tokens <= body.context_max_tokens
        )
        incoming_effective_end_clause = (
            true()
            if body.effective_to is None
            else LlmRate.effective_from < body.effective_to
        )
        overlap = session.execute(
            select(LlmRate.id).where(
                LlmRate.provider == values["provider"],
                LlmRate.model == body.model,
                or_(
                    LlmRate.context_max_tokens.is_(None),
                    LlmRate.context_max_tokens >= body.context_min_tokens,
                ),
                incoming_context_end_clause,
                or_(
                    LlmRate.effective_to.is_(None),
                    LlmRate.effective_to > body.effective_from,
                ),
                incoming_effective_end_clause,
            )
        ).first()
        if overlap:
            session.rollback()
            raise ApiException(
                409,
                "RATE_RANGE_OVERLAP",
                "Rate effective range overlaps an existing version",
            )
        rate = LlmRate(id=uuid.uuid4().hex, created_by=context.user_id, **values)
        session.add(rate)
        session.commit()
        session.refresh(rate)
        # has_active_rate caches this lookup on the shared-key hot path; an
        # admin edit must be visible to the next call, not in 60 seconds.
        invalidate_rate_cache(request.app.state.system_engine)
        return LlmRateOut.model_validate(rate)
