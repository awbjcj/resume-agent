from sqlalchemy import text
from sqlalchemy.engine import Engine

from resume_agent.tracking.dedup import compute_dedup_key


def ensure_dedup_key_column(engine: Engine) -> None:
    """Idempotently add ``jobs.dedup_key`` and backfill it from company/title."""
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))]
        if not cols:
            return
        if "dedup_key" not in cols:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN dedup_key VARCHAR"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_jobs_dedup_key ON jobs (dedup_key)"))
        rows = conn.execute(
            text("SELECT id, company, title FROM jobs WHERE dedup_key IS NULL")
        ).fetchall()
        for row_id, company, title in rows:
            key = compute_dedup_key(company, title)
            if key:
                conn.execute(
                    text("UPDATE jobs SET dedup_key = :k WHERE id = :i"),
                    {"k": key, "i": row_id},
                )


def ensure_posted_at_column(engine: Engine) -> None:
    """Idempotently add the ``jobs.posted_at`` column (source-derived posting date)."""
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))]
        if not cols:
            return
        if "posted_at" not in cols:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN posted_at DATETIME"))
