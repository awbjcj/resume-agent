import json

from sqlalchemy import text
from sqlalchemy.engine import Engine

from resume_agent.tracking.dedup import compute_content_fingerprint, compute_dedup_key
from resume_agent.taxonomy.location import (
    StructuredLocation,
    build_locations,
    location_instances_from_criteria,
)
from resume_agent.taxonomy.industries import clean_industry_label
from resume_agent.tracking.tables import utcnow


def ensure_job_location_instances(engine: Engine) -> None:
    """Backfill and renormalize canonical location arrays for persisted jobs."""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))}
        if not {"id", "location", "criteria_json"}.issubset(cols):
            return
        rows = conn.execute(
            text(
                "SELECT id, location, criteria_json FROM jobs "
                "WHERE location IS NOT NULL"
            )
        ).fetchall()
        for row_id, raw_location, raw_criteria in rows:
            if isinstance(raw_criteria, str):
                try:
                    parsed = json.loads(raw_criteria)
                    criteria = parsed if isinstance(parsed, dict) else {}
                except json.JSONDecodeError:
                    criteria = {}
            else:
                criteria = dict(raw_criteria or {})
            raw_instances = criteria.get("locations")
            if isinstance(raw_instances, list) and any(
                isinstance(item, dict) for item in raw_instances
            ):
                locations = location_instances_from_criteria(criteria)
            else:
                legacy = criteria.get("location_parts")
                primary = None
                if isinstance(legacy, dict):
                    primary = StructuredLocation(
                        city=legacy.get("city"),
                        region=legacy.get("region"),
                        country=legacy.get("country"),
                        is_us=bool(legacy.get("is_us")),
                        raw=legacy.get("raw"),
                    )
                locations = build_locations(str(raw_location), primary=primary)
            if not locations:
                continue
            serialized = [location.as_dict() for location in locations]
            criteria["locations"] = serialized
            criteria["location_parts"] = serialized[0]
            normalized = json.dumps(criteria)
            if normalized != raw_criteria:
                conn.execute(
                    text("UPDATE jobs SET criteria_json = :criteria WHERE id = :id"),
                    {"criteria": normalized, "id": row_id},
                )


def ensure_industry_labels_capitalized(engine: Engine) -> None:
    """Idempotently capitalize persisted job-industry display labels."""
    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))}
        if not {"id", "criteria_json"}.issubset(cols):
            return
        rows = conn.execute(
            text("SELECT id, criteria_json FROM jobs WHERE criteria_json IS NOT NULL")
        ).fetchall()
        for row_id, raw_criteria in rows:
            if isinstance(raw_criteria, str):
                try:
                    parsed = json.loads(raw_criteria)
                except json.JSONDecodeError:
                    continue
            else:
                parsed = raw_criteria
            if not isinstance(parsed, dict):
                continue
            label = clean_industry_label(parsed.get("industry"))
            if label is None or label == parsed.get("industry"):
                continue
            parsed["industry"] = label
            conn.execute(
                text("UPDATE jobs SET criteria_json = :criteria WHERE id = :id"),
                {"criteria": json.dumps(parsed), "id": row_id},
            )


def ensure_dedup_key_column(engine: Engine) -> None:
    """Idempotently add ``jobs.dedup_key`` and backfill it from company/title."""
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))]
        if not cols:
            return
        if "dedup_key" not in cols:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN dedup_key VARCHAR"))
        conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_jobs_dedup_key ON jobs (dedup_key)")
        )
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
            category = (
                "relevance" if str(reason).startswith("off-target role") else "filtered"
            )
            conn.execute(
                text("UPDATE jobs SET reject_category = :c WHERE id = :i"),
                {"c": category, "i": row_id},
            )


def ensure_gate_override_column(engine: Engine) -> None:
    """Idempotently add the manual discovery-gate override flag."""
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))]
        if not cols:
            return
        if "gate_override" not in cols:
            conn.execute(
                text(
                    "ALTER TABLE jobs ADD COLUMN gate_override BOOLEAN "
                    "NOT NULL DEFAULT 0"
                )
            )


def ensure_content_fingerprint_column(engine: Engine) -> None:
    """Idempotently add ``jobs.content_fingerprint`` and backfill it for every row."""
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))]
        if not cols:
            return
        if "content_fingerprint" not in cols:
            conn.execute(
                text("ALTER TABLE jobs ADD COLUMN content_fingerprint VARCHAR")
            )
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


def ensure_industry_pending_column(engine: Engine) -> None:
    """Idempotently add ``jobs.industry_pending`` and backfill it once.

    The revisit set used to be found with ``criteria_json LIKE '%"_industry_
    candidate"%'`` — an unindexed full scan of the jobs table on every extract
    pass, and one that grew with the table rather than with the work. The
    backfill runs here, at ``init_db``, so existing rows migrate on first start
    and the ``LIKE`` never appears on the hot path again.
    """
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))]
        if not cols:
            return
        fresh = "industry_pending" not in cols
        if fresh:
            conn.execute(
                text(
                    "ALTER TABLE jobs ADD COLUMN industry_pending BOOLEAN "
                    "NOT NULL DEFAULT 0"
                )
            )
        conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_jobs_industry_pending "
                "ON jobs (industry_pending)"
            )
        )
        if fresh:
            conn.execute(
                text(
                    "UPDATE jobs SET industry_pending = 1 WHERE "
                    "CAST(criteria_json AS TEXT) LIKE '%\"_industry_candidate\"%' "
                    "OR CAST(criteria_json AS TEXT) LIKE '%\"sic_major\"%'"
                )
            )


def ensure_url_index(engine: Engine) -> None:
    """Idempotently index jobs.url (find_existing's first dedupe probe)."""
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))]
        if not cols:
            return
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_jobs_url ON jobs (url)"))


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
            conn.execute(
                text(
                    "UPDATE resume_versions SET origin = 'tailor' WHERE origin IS NULL"
                )
            )
        if "instruction" not in cols:
            conn.execute(
                text("ALTER TABLE resume_versions ADD COLUMN instruction VARCHAR")
            )
        if "parent_version_id" not in cols:
            conn.execute(
                text("ALTER TABLE resume_versions ADD COLUMN parent_version_id INTEGER")
            )


def ensure_cover_letter_revision_columns(engine: Engine) -> None:
    """Idempotently add revision lineage columns to ``cover_letters``."""
    cols = _table_columns(engine, "cover_letters")
    if not cols:
        return
    with engine.begin() as conn:
        if "origin" not in cols:
            conn.execute(text("ALTER TABLE cover_letters ADD COLUMN origin VARCHAR"))
            conn.execute(
                text("UPDATE cover_letters SET origin = 'draft' WHERE origin IS NULL")
            )
        if "instruction" not in cols:
            conn.execute(
                text("ALTER TABLE cover_letters ADD COLUMN instruction VARCHAR")
            )
        if "parent_id" not in cols:
            conn.execute(text("ALTER TABLE cover_letters ADD COLUMN parent_id INTEGER"))


def ensure_application_cover_letter_id_column(engine: Engine) -> None:
    """Idempotently add ``applications.cover_letter_id``."""
    cols = _table_columns(engine, "applications")
    if not cols:
        return
    if "cover_letter_id" not in cols:
        with engine.begin() as conn:
            conn.execute(
                text("ALTER TABLE applications ADD COLUMN cover_letter_id INTEGER")
            )


def ensure_resume_version_attempt_columns(engine: Engine) -> None:
    """Idempotently add ``resume_versions.attempt``/``tailor_model``.

    Existing rows predate the attempt concept but are, by definition, a job's
    first tailoring; backfilling to 1 (not the column default of 0) keeps
    _next_attempt()'s "max + 1" logic from colliding with them on redo.
    """
    cols = _table_columns(engine, "resume_versions")
    if not cols:
        return
    with engine.begin() as conn:
        if "attempt" not in cols:
            conn.execute(
                text(
                    "ALTER TABLE resume_versions ADD COLUMN attempt INTEGER NOT NULL DEFAULT 0"
                )
            )
            conn.execute(
                text("UPDATE resume_versions SET attempt = 1 WHERE attempt = 0")
            )
        if "tailor_model" not in cols:
            conn.execute(
                text("ALTER TABLE resume_versions ADD COLUMN tailor_model VARCHAR")
            )


def ensure_resume_version_gate_reviewers_column(engine: Engine) -> None:
    """Idempotently add ``resume_versions.gate_reviewers_json``.

    Left NULL on existing rows (rather than backfilled) - the gate roster
    active when they were tailored is not recoverable from the row itself, and
    NULL is the caller-facing signal to fall back to the current review config.
    """
    cols = _table_columns(engine, "resume_versions")
    if not cols:
        return
    with engine.begin() as conn:
        if "gate_reviewers_json" not in cols:
            conn.execute(
                text("ALTER TABLE resume_versions ADD COLUMN gate_reviewers_json JSON")
            )


def ensure_resume_version_evidence_portfolio_columns(engine: Engine) -> None:
    """Add nullable frozen portfolio fields; legacy rows intentionally stay NULL."""
    cols = _table_columns(engine, "resume_versions")
    if not cols:
        return
    with engine.begin() as conn:
        if "evidence_portfolio_json" not in cols:
            conn.execute(
                text(
                    "ALTER TABLE resume_versions ADD COLUMN "
                    "evidence_portfolio_json JSON"
                )
            )
        if "evidence_portfolio_status" not in cols:
            conn.execute(
                text(
                    "ALTER TABLE resume_versions ADD COLUMN "
                    "evidence_portfolio_status VARCHAR"
                )
            )


def ensure_resume_version_taxonomy_columns(engine: Engine) -> None:
    """Idempotently add taxonomy provenance columns to ``resume_versions``.

    This is distinct from ``ensure_resume_version_revision_columns``, which
    adds resume-lineage fields rather than the taxonomy snapshot used to create
    a version.
    """
    cols = _table_columns(engine, "resume_versions")
    if not cols:
        return
    with engine.begin() as conn:
        if "taxonomy_revision" not in cols:
            conn.execute(
                text("ALTER TABLE resume_versions ADD COLUMN taxonomy_revision VARCHAR")
            )
        if "taxonomy_manifest_json" not in cols:
            conn.execute(
                text(
                    "ALTER TABLE resume_versions "
                    "ADD COLUMN taxonomy_manifest_json JSON"
                )
            )


def ensure_agent_metadata_columns(engine: Engine) -> None:
    """Idempotently add nullable skill and agent-run provenance columns."""
    jobs = _table_columns(engine, "jobs")
    resumes = _table_columns(engine, "resume_versions")
    covers = _table_columns(engine, "cover_letters")
    with engine.begin() as conn:
        if jobs and "analysis_meta_json" not in jobs:
            conn.execute(text("ALTER TABLE jobs ADD COLUMN analysis_meta_json JSON"))
        if resumes and "skill_uses_json" not in resumes:
            conn.execute(
                text("ALTER TABLE resume_versions ADD COLUMN skill_uses_json JSON")
            )
        if covers and "skill_uses_json" not in covers:
            conn.execute(
                text("ALTER TABLE cover_letters ADD COLUMN skill_uses_json JSON")
            )


def ensure_application_submitted_events(engine: Engine) -> None:
    """Turn each Application.submitted_at into a real timeline event.

    Every submitted application already carries one true, unambiguous date;
    dropping it would make the first cycle-time chart wrong for no reason.
    Status is NOT backfilled: an `interview` status implies an interview
    happened but carries no date, and an undated synthetic event corrupts the
    very numbers the timeline exists to produce. `source="migration"` keeps
    backfilled rows distinguishable forever.

    No companion table-creation migration exists: `init_db` calls
    `SQLModel.metadata.create_all` before the ensure_* sequence, which builds
    `application_events` and its indexes. `ensure_*` is only for ALTER-shaped
    changes to tables already present in deployed databases.
    """
    with engine.begin() as conn:
        tables = {
            row[0]
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            )
        }
        if not {"applications", "application_events"}.issubset(tables):
            return
        rows = conn.execute(
            text(
                "SELECT a.id, a.submitted_at FROM applications a "
                "WHERE a.submitted_at IS NOT NULL AND NOT EXISTS ("
                "  SELECT 1 FROM application_events e "
                "  WHERE e.application_id = a.id "
                "    AND e.kind = 'application_submitted')"
            )
        ).fetchall()
        for application_id, submitted_at in rows:
            conn.execute(
                text(
                    "INSERT INTO application_events ("
                    "  application_id, kind, sequence, occurred_at, all_day, "
                    "  result, source, schema_version, created_at, updated_at"
                    ") VALUES ("
                    "  :application_id, 'application_submitted', 1, :occurred_at, 1, "
                    "  'advanced', 'migration', 1, :now, :now)"
                ),
                {
                    "application_id": application_id,
                    "occurred_at": submitted_at,
                    "now": utcnow(),
                },
            )


def ensure_application_event_sequence_override_column(engine: Engine) -> None:
    """Persist whether an event sequence was explicitly chosen by the user.

    Legacy rows cannot reveal that provenance. Treat their effective value as
    explicit so a later insert/edit/delete cannot silently destroy ordering a
    user may have chosen. Users can clear an override explicitly afterward.
    """
    cols = _table_columns(engine, "application_events")
    if cols and "sequence_override" not in cols:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE application_events "
                    "ADD COLUMN sequence_override INTEGER"
                )
            )
            conn.execute(
                text(
                    "UPDATE application_events "
                    "SET sequence_override = sequence"
                )
            )
