import uuid
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from resume_agent.config import get_settings

# Import tables so their metadata is registered before create_all().
from resume_agent.tracking import tables  # noqa: F401
from resume_agent.tracking.migrate import (
    ensure_application_cover_letter_id_column,
    ensure_agent_metadata_columns,
    ensure_archived_at_column,
    ensure_content_fingerprint_column,
    ensure_cover_letter_revision_columns,
    ensure_dedup_key_column,
    ensure_gate_override_column,
    ensure_industry_pending_column,
    ensure_industry_labels_capitalized,
    ensure_job_location_instances,
    ensure_posted_at_column,
    ensure_reject_category_column,
    ensure_resume_version_attempt_columns,
    ensure_resume_version_evidence_portfolio_columns,
    ensure_resume_version_gate_reviewers_column,
    ensure_resume_version_revision_columns,
    ensure_resume_version_taxonomy_columns,
    ensure_url_index,
)


def _ensure_sqlite_dir(url: str) -> None:
    """Create the parent directory for a sqlite file URL if needed."""
    prefix = "sqlite:///"
    if url.startswith(prefix):
        db_path = url[len(prefix) :]
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
        # SQLite's shared-cache URI mode gives every thread (FastAPI's request
        # threadpool, RunManager workers, the lifespan that ran init_db) its own
        # DBAPI connection with an independent transaction state, while all of
        # them still see the same in-memory schema/data. A plain StaticPool
        # (one physical connection reused by every thread) makes concurrent
        # sessions share one transaction state, so interleaved BEGIN/COMMIT
        # calls from two threads intermittently raised "Could not refresh
        # instance" ORM errors under real concurrency (e.g. RunManager's
        # background worker racing a request thread's poll). The cache is
        # keyed by name, so each engine gets a unique one -- otherwise every
        # `make_engine("sqlite://")` call (one per test) would share a single
        # process-wide database and collide on `CREATE TABLE`.
        name = uuid.uuid4().hex
        return create_engine(
            f"sqlite:///file:{name}?mode=memory&cache=shared&uri=true",
            echo=False,
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
    ensure_gate_override_column(engine)
    ensure_content_fingerprint_column(engine)
    ensure_industry_pending_column(engine)
    ensure_industry_labels_capitalized(engine)
    ensure_job_location_instances(engine)
    ensure_resume_version_revision_columns(engine)
    ensure_resume_version_attempt_columns(engine)
    ensure_resume_version_gate_reviewers_column(engine)
    ensure_resume_version_evidence_portfolio_columns(engine)
    ensure_resume_version_taxonomy_columns(engine)
    ensure_cover_letter_revision_columns(engine)
    ensure_application_cover_letter_id_column(engine)
    ensure_agent_metadata_columns(engine)
    ensure_url_index(engine)


def get_session(engine: Engine) -> Session:
    return Session(engine)
