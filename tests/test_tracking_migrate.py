from sqlalchemy import text

from resume_agent.db import init_db, make_engine
from resume_agent.tracking.migrate import (
    ensure_application_cover_letter_id_column,
    ensure_cover_letter_revision_columns,
    ensure_resume_version_attempt_columns,
    ensure_resume_version_revision_columns,
)


def test_revision_migrations_backfill_origins():
    engine = make_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE resume_versions ("
                "id INTEGER PRIMARY KEY, job_id INTEGER, round INTEGER)"
            )
        )
        conn.execute(text("INSERT INTO resume_versions (id, job_id, round) VALUES (1, 1, 1)"))
        conn.execute(
            text("CREATE TABLE cover_letters (id INTEGER PRIMARY KEY, job_id INTEGER)")
        )
        conn.execute(text("INSERT INTO cover_letters (id, job_id) VALUES (1, 1)"))
        conn.execute(text("CREATE TABLE applications (id INTEGER PRIMARY KEY, job_id INTEGER)"))

    ensure_resume_version_revision_columns(engine)
    ensure_cover_letter_revision_columns(engine)
    ensure_application_cover_letter_id_column(engine)

    with engine.begin() as conn:
        resume_origin = conn.execute(text("SELECT origin FROM resume_versions")).scalar()
        cover_origin = conn.execute(text("SELECT origin FROM cover_letters")).scalar()
        app_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(applications)"))]

    assert resume_origin == "tailor"
    assert cover_origin == "draft"
    assert "cover_letter_id" in app_cols


def test_init_db_creates_revision_columns():
    engine = make_engine("sqlite://")
    init_db(engine)
    with engine.begin() as conn:
        resume_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(resume_versions)"))]
        cover_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(cover_letters)"))]
        app_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(applications)"))]

    assert {"origin", "instruction", "parent_version_id"}.issubset(resume_cols)
    assert {"origin", "instruction", "parent_id"}.issubset(cover_cols)
    assert "cover_letter_id" in app_cols


def test_attempt_migration_backfills_existing_rows_to_attempt_one():
    engine = make_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE resume_versions ("
                "id INTEGER PRIMARY KEY, job_id INTEGER, round INTEGER)"
            )
        )
        conn.execute(text("INSERT INTO resume_versions (id, job_id, round) VALUES (1, 1, 1)"))

    ensure_resume_version_attempt_columns(engine)

    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(resume_versions)"))]
        attempt = conn.execute(text("SELECT attempt FROM resume_versions")).scalar()
        model = conn.execute(text("SELECT tailor_model FROM resume_versions")).scalar()

    assert {"attempt", "tailor_model"}.issubset(cols)
    # Rows written before this feature existed are, by definition, the job's
    # first (and only) attempt so far -- backfilling to 0 would collide with
    # _next_attempt()'s "max + 1" logic on the very next redo.
    assert attempt == 1
    assert model is None


def test_init_db_creates_attempt_columns():
    engine = make_engine("sqlite://")
    init_db(engine)
    with engine.begin() as conn:
        resume_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(resume_versions)"))]

    assert {"attempt", "tailor_model"}.issubset(resume_cols)
