import pytest
from sqlalchemy import text

from resume_agent.db import init_db, make_engine
from resume_agent.api.schemas.jobs import ResumeVersionOut
from resume_agent.tracking.migrate import (
    ensure_application_cover_letter_id_column,
    ensure_cover_letter_revision_columns,
    ensure_resume_version_attempt_columns,
    ensure_resume_version_evidence_portfolio_columns,
    ensure_resume_version_gate_reviewers_column,
    ensure_resume_version_revision_columns,
    ensure_resume_version_taxonomy_columns,
)
from resume_agent.career_skills.models import read_job_analysis_meta, read_skill_uses


def test_revision_migrations_backfill_origins():
    engine = make_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE resume_versions ("
                "id INTEGER PRIMARY KEY, job_id INTEGER, round INTEGER)"
            )
        )
        conn.execute(
            text("INSERT INTO resume_versions (id, job_id, round) VALUES (1, 1, 1)")
        )
        conn.execute(
            text("CREATE TABLE cover_letters (id INTEGER PRIMARY KEY, job_id INTEGER)")
        )
        conn.execute(text("INSERT INTO cover_letters (id, job_id) VALUES (1, 1)"))
        conn.execute(
            text("CREATE TABLE applications (id INTEGER PRIMARY KEY, job_id INTEGER)")
        )

    ensure_resume_version_revision_columns(engine)
    ensure_cover_letter_revision_columns(engine)
    ensure_application_cover_letter_id_column(engine)

    with engine.begin() as conn:
        resume_origin = conn.execute(
            text("SELECT origin FROM resume_versions")
        ).scalar()
        cover_origin = conn.execute(text("SELECT origin FROM cover_letters")).scalar()
        app_cols = [
            row[1] for row in conn.execute(text("PRAGMA table_info(applications)"))
        ]

    assert resume_origin == "tailor"
    assert cover_origin == "draft"
    assert "cover_letter_id" in app_cols


def test_init_db_creates_revision_columns():
    engine = make_engine("sqlite://")
    init_db(engine)
    with engine.begin() as conn:
        resume_cols = [
            row[1] for row in conn.execute(text("PRAGMA table_info(resume_versions)"))
        ]
        cover_cols = [
            row[1] for row in conn.execute(text("PRAGMA table_info(cover_letters)"))
        ]
        app_cols = [
            row[1] for row in conn.execute(text("PRAGMA table_info(applications)"))
        ]

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
        conn.execute(
            text("INSERT INTO resume_versions (id, job_id, round) VALUES (1, 1, 1)")
        )

    ensure_resume_version_attempt_columns(engine)

    with engine.begin() as conn:
        cols = [
            row[1] for row in conn.execute(text("PRAGMA table_info(resume_versions)"))
        ]
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
        resume_cols = [
            row[1] for row in conn.execute(text("PRAGMA table_info(resume_versions)"))
        ]

    assert {"attempt", "tailor_model"}.issubset(resume_cols)


def test_gate_reviewers_migration_leaves_existing_rows_null():
    engine = make_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE resume_versions ("
                "id INTEGER PRIMARY KEY, job_id INTEGER, round INTEGER)"
            )
        )
        conn.execute(
            text("INSERT INTO resume_versions (id, job_id, round) VALUES (1, 1, 1)")
        )

    ensure_resume_version_gate_reviewers_column(engine)

    with engine.begin() as conn:
        cols = [
            row[1] for row in conn.execute(text("PRAGMA table_info(resume_versions)"))
        ]
        gate_reviewers = conn.execute(
            text("SELECT gate_reviewers_json FROM resume_versions")
        ).scalar()

    assert "gate_reviewers_json" in cols
    # NULL, not backfilled -- the gate roster active for a pre-migration row is
    # not recoverable, and NULL is the read-side signal to fall back to the
    # current review config instead of misreporting an empty roster.
    assert gate_reviewers is None


def test_gate_reviewers_migration_is_idempotent():
    engine = make_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE resume_versions ("
                "id INTEGER PRIMARY KEY, job_id INTEGER, round INTEGER)"
            )
        )
    ensure_resume_version_gate_reviewers_column(engine)
    ensure_resume_version_gate_reviewers_column(engine)  # must not raise


def test_init_db_creates_gate_reviewers_column():
    engine = make_engine("sqlite://")
    init_db(engine)
    with engine.begin() as conn:
        resume_cols = [
            row[1] for row in conn.execute(text("PRAGMA table_info(resume_versions)"))
        ]

    assert "gate_reviewers_json" in resume_cols


def test_evidence_portfolio_migration_is_additive_null_and_idempotent():
    engine = make_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE resume_versions ("
                "id INTEGER PRIMARY KEY, job_id INTEGER, round INTEGER)"
            )
        )
        conn.execute(
            text("INSERT INTO resume_versions (id, job_id, round) VALUES (1, 1, 1)")
        )

    ensure_resume_version_evidence_portfolio_columns(engine)
    ensure_resume_version_evidence_portfolio_columns(engine)

    with engine.begin() as conn:
        cols = [
            row[1] for row in conn.execute(text("PRAGMA table_info(resume_versions)"))
        ]
        values = conn.execute(
            text(
                "SELECT evidence_portfolio_json, evidence_portfolio_status "
                "FROM resume_versions"
            )
        ).one()

    assert {"evidence_portfolio_json", "evidence_portfolio_status"}.issubset(cols)
    assert values == (None, None)


def test_resume_version_taxonomy_migration_is_additive_and_idempotent():
    engine = make_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE resume_versions ("
                "id INTEGER PRIMARY KEY, job_id INTEGER, round INTEGER)"
            )
        )
        conn.execute(
            text("INSERT INTO resume_versions (id, job_id, round) VALUES (1, 1, 1)")
        )

    ensure_resume_version_taxonomy_columns(engine)
    ensure_resume_version_taxonomy_columns(engine)

    with engine.begin() as conn:
        cols = [
            row[1] for row in conn.execute(text("PRAGMA table_info(resume_versions)"))
        ]
        values = conn.execute(
            text(
                "SELECT taxonomy_revision, taxonomy_manifest_json FROM resume_versions"
            )
        ).one()

    assert {"taxonomy_revision", "taxonomy_manifest_json"}.issubset(cols)
    assert values == (None, None)


def test_init_db_upgrades_legacy_resume_versions_with_taxonomy_columns():
    engine = make_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE resume_versions ("
                "id INTEGER PRIMARY KEY, job_id INTEGER, round INTEGER)"
            )
        )

    init_db(engine)

    with engine.begin() as conn:
        cols = [
            row[1] for row in conn.execute(text("PRAGMA table_info(resume_versions)"))
        ]

    assert {"taxonomy_revision", "taxonomy_manifest_json"}.issubset(cols)


def test_legacy_resume_version_reports_revision_unknown():
    version = ResumeVersionOut.model_validate(
        {
            "id": 1,
            "jobId": 1,
            "round": 0,
            "reviewScore": None,
            "factCheckPassed": False,
            "pdfPath": None,
            "critiqueJson": None,
            "createdAt": "2026-01-01T00:00:00Z",
            "taxonomyRevision": None,
        }
    )

    assert version.revision_unknown is True
    assert "taxonomyRevision" not in version.model_dump(by_alias=True)


def test_agent_metadata_migration_is_additive_and_idempotent():
    engine = make_engine("sqlite://")
    init_db(engine)
    init_db(engine)
    with engine.begin() as conn:
        jobs = [row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))]
        resumes = [
            row[1] for row in conn.execute(text("PRAGMA table_info(resume_versions)"))
        ]
        covers = [
            row[1] for row in conn.execute(text("PRAGMA table_info(cover_letters)"))
        ]
        table = conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='h1b_company_evidence'"
            )
        ).scalar()
    assert "analysis_meta_json" in jobs
    assert "skill_uses_json" in resumes
    assert "skill_uses_json" in covers
    assert table == "h1b_company_evidence"


def test_metadata_readers_preserve_legacy_none_and_reject_corruption():
    assert read_skill_uses(None) == []
    assert read_job_analysis_meta(None) is None
    with pytest.raises(ValueError):
        read_skill_uses({"not": "a list"})
    with pytest.raises(ValueError):
        read_job_analysis_meta([])
