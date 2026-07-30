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
