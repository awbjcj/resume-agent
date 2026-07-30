from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from resume_agent.api.deps import require_admin
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.admin_system import (
    SystemDefaults,
    SystemDefaultsUpdate,
    UsageReport,
    UserUsage,
)
from resume_agent.tenancy.context import UserContext
from resume_agent.tenancy.limits import (
    DEFAULT_MAX_ACTIVE_JOBS,
    DEFAULT_MAX_CONCURRENT_RUNS,
    DEFAULT_WEEKLY_TOKEN_BUDGET,
    system_default,
)
from resume_agent.tenancy.system_db import SystemSetting, UsageEvent, User

router = APIRouter(prefix="/admin/system", tags=["admin"])

_DEFAULTS = {
    "weekly_token_budget": DEFAULT_WEEKLY_TOKEN_BUDGET,
    "max_active_jobs": DEFAULT_MAX_ACTIVE_JOBS,
    "max_concurrent_runs": DEFAULT_MAX_CONCURRENT_RUNS,
}


@router.get("/defaults")
def get_defaults(
    request: Request, _context: UserContext = Depends(require_admin)
) -> SystemDefaults:
    engine = request.app.state.system_engine
    return SystemDefaults(
        **{
            key: system_default(engine, key, fallback)
            for key, fallback in _DEFAULTS.items()
        }
    )


@router.put("/defaults")
def put_defaults(
    body: SystemDefaultsUpdate,
    request: Request,
    _context: UserContext = Depends(require_admin),
) -> SystemDefaults:
    if "weekly_token_budget" in body.model_fields_set:
        raise ApiException(
            422,
            "TOKEN_QUOTA_DEPRECATED",
            "Token budgets are analytics-only; manage member cost quotas instead",
        )
    with Session(request.app.state.system_engine) as session:
        for key in ("max_active_jobs", "max_concurrent_runs"):
            row = session.get(SystemSetting, key)
            value = str(getattr(body, key))
            if row is None:
                session.add(SystemSetting(key=key, value=value))
            else:
                row.value = value
        session.commit()
    return get_defaults(request, _context)


@router.get("/usage")
def usage_report(
    request: Request,
    days: int = Query(default=7, ge=1, le=90),
    _context: UserContext = Depends(require_admin),
) -> UsageReport:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    with Session(request.app.state.system_engine) as session:
        rows = session.execute(
            select(
                UsageEvent.user_id,
                func.coalesce(User.username, UsageEvent.user_id),
                func.sum(
                    case(
                        (UsageEvent.own_key.is_(False), UsageEvent.weighted_total),
                        else_=0.0,
                    )
                ),
                func.sum(
                    case(
                        (UsageEvent.own_key.is_(True), UsageEvent.weighted_total),
                        else_=0.0,
                    )
                ),
                func.count(UsageEvent.id),
            )
            .outerjoin(User, User.id == UsageEvent.user_id)
            .where(UsageEvent.ts >= cutoff)
            .group_by(UsageEvent.user_id, User.username)
        ).all()
    return UsageReport(
        users=[
            UserUsage(
                user_id=row[0],
                username=row[1],
                weighted_total=float(row[2] or 0),
                own_key_weighted_total=float(row[3] or 0),
                calls=int(row[4]),
            )
            for row in rows
        ]
    )
