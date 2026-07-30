from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from resume_agent.tenancy.system_db import LoginAttempt, User


@dataclass(frozen=True)
class Budget:
    scope: str
    limit: int
    window: timedelta


BUDGETS = (
    Budget("email_ip", 10, timedelta(minutes=15)),
    Budget("email", 20, timedelta(hours=1)),
    Budget("ip", 50, timedelta(hours=1)),
    Budget("resend_email", 3, timedelta(hours=1)),
)
IP_ONLY = frozenset({"ip"})
RESEND_ONLY = frozenset({"resend_email"})
DEFAULT_SCOPES = frozenset({"email_ip", "email", "ip"})
_MAX_WINDOW = timedelta(hours=1)
_SIGNUP_WINDOW = timedelta(days=1)


def _identifiers(email: str, ip: str) -> dict[str, str]:
    folded = email.casefold()
    return {
        "email_ip": f"{folded}|{ip}",
        "email": folded,
        "ip": ip,
        "resend_email": folded,
    }


def _blocked(
    session: Session,
    identifiers: dict[str, str],
    scopes: frozenset[str],
    moment: datetime,
) -> bool:
    for budget in BUDGETS:
        if budget.scope not in scopes:
            continue
        count = session.execute(
            select(func.count())
            .select_from(LoginAttempt)
            .where(
                LoginAttempt.scope == budget.scope,
                LoginAttempt.identifier == identifiers[budget.scope],
                LoginAttempt.occurred_at > moment - budget.window,
            )
        ).scalar_one()
        if count >= budget.limit:
            return True
    return False


def blocked(
    engine: Engine,
    *,
    email: str,
    ip: str,
    scopes: frozenset[str] = DEFAULT_SCOPES,
    now: datetime | None = None,
) -> bool:
    moment = now or datetime.now(timezone.utc)
    with Session(engine) as session:
        return _blocked(session, _identifiers(email, ip), scopes, moment)


def consume(
    engine: Engine,
    *,
    email: str,
    ip: str,
    scopes: frozenset[str] = DEFAULT_SCOPES,
    now: datetime | None = None,
) -> bool:
    """Atomically reject an exhausted budget or record this event."""
    moment = now or datetime.now(timezone.utc)
    identifiers = _identifiers(email, ip)
    with Session(engine) as session:
        session.execute(text("BEGIN IMMEDIATE"))
        session.execute(
            delete(LoginAttempt).where(LoginAttempt.occurred_at < moment - _MAX_WINDOW)
        )
        if _blocked(session, identifiers, scopes, moment):
            session.rollback()
            return False
        for scope in scopes:
            session.add(
                LoginAttempt(
                    scope=scope,
                    identifier=identifiers[scope],
                    occurred_at=moment,
                )
            )
        session.commit()
    return True


def consume_global_signup(
    engine: Engine, *, limit: int, now: datetime | None = None
) -> bool:
    """Atomically enforce a platform-wide pending-signup mail budget."""

    moment = now or datetime.now(timezone.utc)
    with Session(engine) as session:
        session.execute(text("BEGIN IMMEDIATE"))
        session.execute(
            delete(LoginAttempt).where(
                LoginAttempt.scope == "signup_global",
                LoginAttempt.occurred_at < moment - _SIGNUP_WINDOW,
            )
        )
        count = session.execute(
            select(func.count())
            .select_from(LoginAttempt)
            .where(
                LoginAttempt.scope == "signup_global",
                LoginAttempt.occurred_at > moment - _SIGNUP_WINDOW,
            )
        ).scalar_one()
        if count >= limit:
            session.rollback()
            return False
        session.add(
            LoginAttempt(
                scope="signup_global",
                identifier="global",
                occurred_at=moment,
            )
        )
        session.commit()
    return True


def record_failure(engine: Engine, *, email: str, ip: str) -> bool:
    return consume(engine, email=email, ip=ip)


def reset(engine: Engine, *, email: str, ip: str) -> None:
    identifiers = _identifiers(email, ip)
    with Session(engine) as session:
        for scope in ("email_ip", "email"):
            session.execute(
                delete(LoginAttempt).where(
                    LoginAttempt.scope == scope,
                    LoginAttempt.identifier == identifiers[scope],
                )
            )
        session.commit()


def register_lockout(user: User, now: datetime) -> None:
    user.failed_login_count = (user.failed_login_count or 0) + 1
    count = user.failed_login_count
    if count % 5:
        return
    if count >= 15:
        user.locked_until = now + timedelta(hours=1)
    elif count >= 10:
        user.locked_until = now + timedelta(minutes=15)
    elif count >= 5:
        user.locked_until = now + timedelta(minutes=1)


def clear_lockout(user: User) -> None:
    user.failed_login_count = 0
    user.locked_until = None


def is_locked(user: User, now: datetime) -> bool:
    deadline = user.locked_until
    if deadline is None:
        return False
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return deadline > now
