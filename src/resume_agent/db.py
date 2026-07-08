from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from resume_agent.config import get_settings
from resume_agent.tracking.migrate import (
    ensure_application_cover_letter_id_column,
    ensure_archived_at_column,
    ensure_content_fingerprint_column,
    ensure_cover_letter_revision_columns,
    ensure_dedup_key_column,
    ensure_posted_at_column,
    ensure_reject_category_column,
    ensure_resume_version_revision_columns,
    ensure_url_index,
)

# Import tables so their metadata is registered before create_all().
from resume_agent.tracking import tables  # noqa: F401


def _ensure_sqlite_dir(url: str) -> None:
    """Create the parent directory for a sqlite file URL if needed."""
    prefix = "sqlite:///"
    if url.startswith(prefix):
        db_path = url[len(prefix):]
        if db_path and db_path != ":memory:":
            Path(db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)


def _is_memory_sqlite(url: str) -> bool:
    """True for an in-memory sqlite URL (`sqlite://` or `sqlite:///:memory:`)."""
    return url in ("sqlite://", "sqlite://:memory:", "sqlite:///:memory:")


def _enable_sqlite_write_concurrency(engine: Engine) -> None:
    """WAL + busy timeout on every connection to a file-backed SQLite DB."""

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


def make_engine(url: str | None = None) -> Engine:
    resolved = url or get_settings().db_url
    _ensure_sqlite_dir(resolved)
    if _is_memory_sqlite(resolved):
        # A single shared connection so every thread (e.g. FastAPI's request
        # threadpool vs. the lifespan that ran init_db) sees the same in-memory
        # database. The default SingletonThreadPool would give each thread its
        # own empty DB. Only in-memory URLs hit this; file/prod is unaffected.
        return create_engine(
            resolved,
            echo=False,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    engine = create_engine(resolved, echo=False)
    if resolved.startswith("sqlite"):
        _enable_sqlite_write_concurrency(engine)
    return engine


def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)
    ensure_dedup_key_column(engine)
    ensure_posted_at_column(engine)
    ensure_archived_at_column(engine)
    ensure_reject_category_column(engine)
    ensure_content_fingerprint_column(engine)
    ensure_resume_version_revision_columns(engine)
    ensure_cover_letter_revision_columns(engine)
    ensure_application_cover_letter_id_column(engine)
    ensure_url_index(engine)


def get_session(engine: Engine) -> Session:
    return Session(engine)
