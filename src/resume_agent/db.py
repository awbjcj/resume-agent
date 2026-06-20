from pathlib import Path

from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from resume_agent.config import get_settings
from resume_agent.tracking.migrate import (
    ensure_archived_at_column,
    ensure_dedup_key_column,
    ensure_posted_at_column,
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


def make_engine(url: str | None = None) -> Engine:
    resolved = url or get_settings().db_url
    _ensure_sqlite_dir(resolved)
    return create_engine(resolved, echo=False)


def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)
    ensure_dedup_key_column(engine)
    ensure_posted_at_column(engine)
    ensure_archived_at_column(engine)


def get_session(engine: Engine) -> Session:
    return Session(engine)
