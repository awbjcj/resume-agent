"""Idempotent additive migrations for the shared system database."""

from sqlalchemy import text
from sqlalchemy.engine import Engine


_USER_COLUMNS = (
    ("email", "VARCHAR(320)"),
    ("email_verified_at", "DATETIME"),
    ("google_sub", "VARCHAR(64)"),
    ("session_epoch", "INTEGER NOT NULL DEFAULT 0"),
    ("failed_login_count", "INTEGER NOT NULL DEFAULT 0"),
    ("locked_until", "DATETIME"),
    ("shared_key_access", "BOOLEAN NOT NULL DEFAULT 1"),
)

_USAGE_COLUMNS = (
    ("cache_write_tokens", "INTEGER NOT NULL DEFAULT 0"),
    ("reasoning_tokens", "INTEGER NOT NULL DEFAULT 0"),
    ("audio_input_tokens", "INTEGER NOT NULL DEFAULT 0"),
    ("audio_output_tokens", "INTEGER NOT NULL DEFAULT 0"),
    ("total_tokens", "INTEGER NOT NULL DEFAULT 0"),
    ("cost_micros", "INTEGER"),
    ("quota_cost_micros", "INTEGER NOT NULL DEFAULT 0"),
    ("tool_cost_micros", "INTEGER NOT NULL DEFAULT 0"),
    ("provider_cost_micros", "INTEGER"),
    ("rate_id", "VARCHAR(32)"),
    ("pricing_status", "VARCHAR(24) NOT NULL DEFAULT 'LEGACY_UNPRICED'"),
    ("reasoning_effort", "VARCHAR(24)"),
    ("reasoning_mode", "VARCHAR(24)"),
)

_LLM_RATE_COLUMNS = (("rate_period", "VARCHAR(16)"),)

_SHARED_KEYS_ALL_ACCOUNTS_MARKER = "migration_shared_keys_all_accounts_v1"


def _columns(connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(text(f"PRAGMA table_info({table})"))}


def migrate_system_db(engine: Engine) -> None:
    with engine.begin() as connection:
        existing = _columns(connection, "users")
        if not existing:
            return
        for name, ddl in _USER_COLUMNS:
            if name not in existing:
                connection.execute(text(f"ALTER TABLE users ADD COLUMN {name} {ddl}"))
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS system_settings ("
                "key VARCHAR(80) PRIMARY KEY, "
                "value VARCHAR(160) NOT NULL, "
                "updated_at DATETIME NOT NULL)"
            )
        )
        migrated_shared_access = connection.execute(
            text("SELECT 1 FROM system_settings WHERE key = :key"),
            {"key": _SHARED_KEYS_ALL_ACCOUNTS_MARKER},
        ).first()
        if migrated_shared_access is None:
            connection.execute(text("UPDATE users SET shared_key_access = 1"))
            connection.execute(
                text(
                    "INSERT INTO system_settings (key, value, updated_at) "
                    "VALUES (:key, 'complete', CURRENT_TIMESTAMP)"
                ),
                {"key": _SHARED_KEYS_ALL_ACCOUNTS_MARKER},
            )
        usage_columns = _columns(connection, "usage_events")
        for name, ddl in _USAGE_COLUMNS:
            if usage_columns and name not in usage_columns:
                connection.execute(
                    text(f"ALTER TABLE usage_events ADD COLUMN {name} {ddl}")
                )
        if usage_columns:
            connection.execute(
                text(
                    "UPDATE usage_events SET "
                    "cache_write_tokens = cache_creation_tokens, "
                    "total_tokens = input_tokens + output_tokens "
                    "WHERE pricing_status = 'LEGACY_UNPRICED'"
                )
            )
        if usage_columns:
            # The global cost/usage aggregates filter on own_key + ts with no
            # user_id predicate, so neither existing usage index could serve
            # them. create_all adds this for a fresh database; existing
            # deployments get it here.
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_usage_events_own_key_ts "
                    "ON usage_events (own_key, ts)"
                )
            )
        connection.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email)")
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_google_sub "
                "ON users (google_sub)"
            )
        )
        reset_columns = _columns(connection, "password_reset_codes")
        if reset_columns and "pending_email" not in reset_columns:
            connection.execute(
                text(
                    "ALTER TABLE password_reset_codes "
                    "ADD COLUMN pending_email VARCHAR(320)"
                )
            )
        rate_columns = _columns(connection, "llm_rates")
        for name, ddl in _LLM_RATE_COLUMNS:
            if rate_columns and name not in rate_columns:
                connection.execute(
                    text(f"ALTER TABLE llm_rates ADD COLUMN {name} {ddl}")
                )
