from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from resume_agent.db import _enable_sqlite_write_concurrency


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SystemBase(DeclarativeBase):
    pass


class User(SystemBase):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('admin', 'user')", name="ck_users_role"),
    )

    id: Mapped[str] = mapped_column(String(12), primary_key=True)
    username: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String(8), nullable=False, default="user")
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    weekly_token_budget: Mapped[int | None] = mapped_column(Integer)
    max_active_jobs: Mapped[int | None] = mapped_column(Integer)
    max_concurrent_runs: Mapped[int | None] = mapped_column(Integer)
    shared_key_access: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    email: Mapped[str | None] = mapped_column(String(320), unique=True, index=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    google_sub: Mapped[str | None] = mapped_column(String(64), unique=True)
    session_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_login_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class InviteCode(SystemBase):
    __tablename__ = "invite_codes"

    id: Mapped[str] = mapped_column(String(12), primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_by: Mapped[str] = mapped_column(String(12), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_by: Mapped[str | None] = mapped_column(String(12))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PendingRegistration(SystemBase):
    __tablename__ = "pending_registrations"

    id: Mapped[str] = mapped_column(String(12), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(64))
    invite_code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class PasswordResetCode(SystemBase):
    __tablename__ = "password_reset_codes"

    id: Mapped[str] = mapped_column(String(12), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pending_email: Mapped[str | None] = mapped_column(String(320))


class OAuthFlow(SystemBase):
    """One-time server-side state for the Google sign-in redirect."""

    __tablename__ = "oauth_flows"
    __table_args__ = (Index("ix_oauth_flows_expires_at", "expires_at"),)

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    state: Mapped[str] = mapped_column(String(2048), nullable=False)
    pkce_verifier: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class LoginAttempt(SystemBase):
    __tablename__ = "login_attempts"
    __table_args__ = (
        Index("ix_login_attempts_scope_id_ts", "scope", "identifier", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    identifier: Mapped[str] = mapped_column(String(400), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


def has_password(user: User) -> bool:
    return bool(user.password_hash)


class ApiToken(SystemBase):
    __tablename__ = "api_tokens"

    id: Mapped[str] = mapped_column(String(12), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UsageEvent(SystemBase):
    __tablename__ = "usage_events"
    # The per-user index serves the per-user aggregates. The two *global*
    # aggregates (global_monthly_cost, global_weekly_usage) filter on own_key +
    # ts with no user_id predicate, so neither existing index applies and both
    # fell back to a full scan of a table that grows one row per LLM call
    # forever.
    __table_args__ = (
        Index("ix_usage_events_user_ts", "user_id", "ts"),
        Index("ix_usage_events_own_key_ts", "own_key", "ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    provider: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(160))
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_creation_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    cache_write_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reasoning_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    audio_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    audio_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    weighted_total: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    own_key: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cost_micros: Mapped[int | None] = mapped_column(Integer)
    quota_cost_micros: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_cost_micros: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_cost_micros: Mapped[int | None] = mapped_column(Integer)
    rate_id: Mapped[str | None] = mapped_column(String(32))
    pricing_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="LEGACY_UNPRICED"
    )
    reasoning_effort: Mapped[str | None] = mapped_column(String(24))
    reasoning_mode: Mapped[str | None] = mapped_column(String(24))


class UsageLineItem(SystemBase):
    __tablename__ = "usage_line_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    usage_event_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    units: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rate_micros: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_micros: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rate_id: Mapped[str] = mapped_column(String(32), nullable=False)


class LlmRate(SystemBase):
    __tablename__ = "llm_rates"
    __table_args__ = (
        Index("ix_llm_rates_lookup", "provider", "model", "effective_from"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(160), nullable=False)
    context_min_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    context_max_tokens: Mapped[int | None] = mapped_column(Integer)
    input_micros_per_million: Mapped[int] = mapped_column(Integer, nullable=False)
    cache_read_micros_per_million: Mapped[int | None] = mapped_column(Integer)
    cache_write_micros_per_million: Mapped[int | None] = mapped_column(Integer)
    output_micros_per_million: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_micros_per_unit: Mapped[int | None] = mapped_column(Integer)
    # None = active for every hour of the day. "peak" / "off_peak" restrict
    # the row to DeepSeek-style time-of-day bands (see costs.py::_rate_period).
    rate_period: Mapped[str | None] = mapped_column(String(16))
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_url: Mapped[str] = mapped_column(String(500), nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(12))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class QuotaTier(SystemBase):
    __tablename__ = "quota_tiers"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    cycle_unit: Mapped[str] = mapped_column(String(8), nullable=False)
    cycle_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    allowance_micros: Mapped[int | None] = mapped_column(Integer)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class QuotaAccount(SystemBase):
    __tablename__ = "quota_accounts"

    user_id: Mapped[str] = mapped_column(String(12), primary_key=True)
    tier_id: Mapped[str] = mapped_column(String(32), nullable=False, default="FREE")
    quota_override_micros: Mapped[int | None] = mapped_column(Integer)
    credit_balance_micros: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    active_period_id: Mapped[str | None] = mapped_column(String(32))
    anchor_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class QuotaPeriod(SystemBase):
    __tablename__ = "quota_periods"
    __table_args__ = (Index("ix_quota_periods_user_start", "user_id", "starts_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    tier_id: Mapped[str] = mapped_column(String(32), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    allowance_micros: Mapped[int | None] = mapped_column(Integer)
    spent_micros: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    credit_spent_micros: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    overage_micros: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class QuotaOperationPreview(SystemBase):
    __tablename__ = "quota_operation_previews"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    created_by: Mapped[str] = mapped_column(String(12), nullable=False)
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_value: Mapped[str | None] = mapped_column(String(32))
    action_type: Mapped[str] = mapped_column(String(24), nullable=False)
    amount_micros: Mapped[int | None] = mapped_column(Integer)
    target_user_ids: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class QuotaOperation(SystemBase):
    __tablename__ = "quota_operations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    preview_id: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_user_id: Mapped[str] = mapped_column(String(12), nullable=False)
    action_type: Mapped[str] = mapped_column(String(24), nullable=False)
    target_type: Mapped[str] = mapped_column(String(16), nullable=False)
    target_value: Mapped[str | None] = mapped_column(String(32))
    amount_micros: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    affected_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class QuotaLedgerEntry(SystemBase):
    __tablename__ = "quota_ledger_entries"
    __table_args__ = (Index("ix_quota_ledger_user_created", "user_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    period_id: Mapped[str | None] = mapped_column(String(32))
    operation_id: Mapped[str | None] = mapped_column(String(32))
    usage_event_id: Mapped[int | None] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    amount_micros: Mapped[int] = mapped_column(Integer, nullable=False)
    recurring_micros: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    credit_micros: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    overage_micros: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    actor_user_id: Mapped[str | None] = mapped_column(String(12))
    reason: Mapped[str | None] = mapped_column(String(500))
    snapshot_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class SystemSetting(SystemBase):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(String(160), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


def system_db_url(data_root: Path | str) -> str:
    return f"sqlite:///{(Path(data_root) / 'system.db').as_posix()}"


def make_system_engine(data_root: Path | str) -> Engine:
    Path(data_root).mkdir(parents=True, exist_ok=True)
    engine = create_engine(system_db_url(data_root), echo=False)
    _enable_sqlite_write_concurrency(engine)
    return engine


def init_system_db(engine: Engine) -> None:
    SystemBase.metadata.create_all(engine)
    # Keep every entry point (API, CLI, restore) on the same additive schema.
    # Local import avoids a module cycle while the declarative models load.
    from resume_agent.tenancy.migrate_system import migrate_system_db

    migrate_system_db(engine)
    from resume_agent.tenancy.costs import seed_llm_rates
    from resume_agent.tenancy.quotas import seed_quota_accounts, seed_quota_tiers

    seed_quota_tiers(engine)
    seed_llm_rates(engine)
    seed_quota_accounts(engine)
