from sqlalchemy import text
from sqlalchemy.engine import Engine

from resume_agent.tracking.dedup import compute_content_fingerprint, compute_dedup_key


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


def ensure_archived_at_column(engine: Engine) -> None:
    """Idempotently add the ``jobs.archived_at`` column (soft-archive timestamp)."""
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))]
        if not cols:
            return
        if "archived_at" not in cols:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN archived_at DATETIME"))
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_jobs_archived_at ON jobs (archived_at)")
        )


def ensure_reject_category_column(engine: Engine) -> None:
    """Idempotently add ``jobs.reject_category`` and classify existing reject reasons."""
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))]
        if not cols:
            return
        if "reject_category" not in cols:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN reject_category VARCHAR"))
        rows = conn.execute(
            text(
                "SELECT id, reject_reason FROM jobs "
                "WHERE reject_reason IS NOT NULL AND reject_category IS NULL"
            )
        ).fetchall()
        for row_id, reason in rows:
            category = "relevance" if str(reason).startswith("off-target role") else "filtered"
            conn.execute(
                text("UPDATE jobs SET reject_category = :c WHERE id = :i"),
                {"c": category, "i": row_id},
            )


def ensure_content_fingerprint_column(engine: Engine) -> None:
    """Idempotently add ``jobs.content_fingerprint`` and backfill it for every row."""
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))]
        if not cols:
            return
        if "content_fingerprint" not in cols:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN content_fingerprint VARCHAR"))
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_jobs_content_fingerprint "
                "ON jobs (content_fingerprint)"
            )
        )
        rows = conn.execute(
            text("SELECT id, jd_text FROM jobs WHERE content_fingerprint IS NULL")
        ).fetchall()
        for row_id, jd_text in rows:
            fingerprint = compute_content_fingerprint(jd_text)
            if fingerprint:
                conn.execute(
                    text("UPDATE jobs SET content_fingerprint = :f WHERE id = :i"),
                    {"f": fingerprint, "i": row_id},
                )


def _table_columns(engine: Engine, table: str) -> list[str]:
    with engine.begin() as conn:
        return [row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))]


def ensure_resume_version_revision_columns(engine: Engine) -> None:
    """Idempotently add revision lineage columns to ``resume_versions``."""
    cols = _table_columns(engine, "resume_versions")
    if not cols:
        return
    with engine.begin() as conn:
        if "origin" not in cols:
            conn.execute(text("ALTER TABLE resume_versions ADD COLUMN origin VARCHAR"))
            conn.execute(text("UPDATE resume_versions SET origin = 'tailor' WHERE origin IS NULL"))
        if "instruction" not in cols:
            conn.execute(text("ALTER TABLE resume_versions ADD COLUMN instruction VARCHAR"))
        if "parent_version_id" not in cols:
            conn.execute(text("ALTER TABLE resume_versions ADD COLUMN parent_version_id INTEGER"))


def ensure_cover_letter_revision_columns(engine: Engine) -> None:
    """Idempotently add revision lineage columns to ``cover_letters``."""
    cols = _table_columns(engine, "cover_letters")
    if not cols:
        return
    with engine.begin() as conn:
        if "origin" not in cols:
            conn.execute(text("ALTER TABLE cover_letters ADD COLUMN origin VARCHAR"))
            conn.execute(text("UPDATE cover_letters SET origin = 'draft' WHERE origin IS NULL"))
        if "instruction" not in cols:
            conn.execute(text("ALTER TABLE cover_letters ADD COLUMN instruction VARCHAR"))
        if "parent_id" not in cols:
            conn.execute(text("ALTER TABLE cover_letters ADD COLUMN parent_id INTEGER"))


def ensure_application_cover_letter_id_column(engine: Engine) -> None:
    """Idempotently add ``applications.cover_letter_id``."""
    cols = _table_columns(engine, "applications")
    if not cols:
        return
    if "cover_letter_id" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE applications ADD COLUMN cover_letter_id INTEGER"))
