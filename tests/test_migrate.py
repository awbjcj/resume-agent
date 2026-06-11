from sqlalchemy import text
from sqlmodel import create_engine

from resume_agent.db import init_db
from resume_agent.tracking.migrate import ensure_dedup_key_column


def test_ensure_adds_column_and_backfills_old_jobs_table():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE jobs (id INTEGER PRIMARY KEY, source VARCHAR, "
                "company VARCHAR, title VARCHAR, jd_text VARCHAR)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO jobs (id, source, company, title, jd_text) "
                "VALUES (1, 'manual', 'Acme Corp', 'Senior Backend Engineer', 'jd')"
            )
        )

    ensure_dedup_key_column(engine)

    with engine.connect() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))]
        assert "dedup_key" in cols
        indexes = [row[1] for row in conn.execute(text("PRAGMA index_list(jobs)"))]
        assert "ix_jobs_dedup_key" in indexes
        key = conn.execute(text("SELECT dedup_key FROM jobs WHERE id = 1")).scalar()
        assert key == "acme corp|backend engineer"


def test_ensure_is_noop_on_current_schema():
    engine = create_engine("sqlite://")
    init_db(engine)
    ensure_dedup_key_column(engine)
