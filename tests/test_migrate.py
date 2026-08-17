import json

from sqlalchemy import text
from sqlmodel import create_engine

from resume_agent.db import init_db
from resume_agent.tracking.migrate import (
    ensure_dedup_key_column,
    ensure_job_location_instances,
    ensure_posted_at_column,
)


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


def test_ensure_posted_at_column_adds_missing_column():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE jobs (id INTEGER PRIMARY KEY, source VARCHAR)"))
    ensure_posted_at_column(engine)
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))]
    assert "posted_at" in cols


def test_ensure_posted_at_column_is_idempotent():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE jobs (id INTEGER PRIMARY KEY, source VARCHAR)"))
    ensure_posted_at_column(engine)
    ensure_posted_at_column(engine)
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))]
    assert cols.count("posted_at") == 1


def test_ensure_archived_at_column_adds_missing_column():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE jobs (id INTEGER PRIMARY KEY, source VARCHAR)"))
    from resume_agent.tracking.migrate import ensure_archived_at_column
    ensure_archived_at_column(engine)
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))]
        indexes = [row[1] for row in conn.execute(text("PRAGMA index_list(jobs)"))]
    assert "archived_at" in cols
    assert "ix_jobs_archived_at" in indexes


def test_ensure_archived_at_column_is_idempotent():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE jobs (id INTEGER PRIMARY KEY, source VARCHAR)"))
    from resume_agent.tracking.migrate import ensure_archived_at_column
    ensure_archived_at_column(engine)
    ensure_archived_at_column(engine)
    with engine.begin() as conn:
        cols = [row[1] for row in conn.execute(text("PRAGMA table_info(jobs)"))]
    assert cols.count("archived_at") == 1


def test_url_index_created(tmp_path):
    from resume_agent.db import init_db, make_engine

    engine = make_engine(f"sqlite:///{tmp_path / 'idx.db'}")
    init_db(engine)
    with engine.begin() as conn:
        names = [row[1] for row in conn.execute(text("PRAGMA index_list(jobs)"))]
    assert "ix_jobs_url" in names


def test_location_instance_migration_backfills_legacy_multi_location_jobs():
    engine = create_engine("sqlite://")
    init_db(engine)
    criteria = {
        "location_parts": {
            "city": "Austin",
            "region": "TX",
            "country": "US",
            "is_us": True,
            "raw": "Austin, TX",
        }
    }
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO jobs (source, location, jd_text, status, criteria_json, "
                "gate_override, industry_pending, schema_version, created_at) "
                "VALUES ('ashby', :location, 'jd', 'shortlisted', :criteria, "
                "0, 0, 1, CURRENT_TIMESTAMP)"
            ),
            {
                "location": "Austin, TX | Toronto, Ontario, Canada",
                "criteria": json.dumps(criteria),
            },
        )
        conn.execute(
            text(
                "INSERT INTO jobs (source, location, jd_text, status, "
                "gate_override, industry_pending, schema_version, created_at) "
                "VALUES ('personio', 'Berlin // Remote', 'jd', 'raw', "
                "0, 0, 1, CURRENT_TIMESTAMP)"
            )
        )

    ensure_job_location_instances(engine)
    ensure_job_location_instances(engine)

    with engine.connect() as conn:
        stored = conn.execute(
            text("SELECT criteria_json FROM jobs ORDER BY id")
        ).scalars().all()
    migrated = json.loads(stored[0])
    assert [item["city"] for item in migrated["locations"]] == ["Austin", "Toronto"]
    assert migrated["locations"][1]["country"] == "CA"
    assert [item["raw"] for item in json.loads(stored[1])["locations"]] == [
        "Berlin",
        "Remote",
    ]
