from sqlalchemy import text

from resume_agent.db import make_engine
from resume_agent.tracking.migrate import (
    ensure_content_fingerprint_column,
    ensure_reject_category_column,
)


def _legacy_engine():
    engine = make_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE jobs (id INTEGER PRIMARY KEY, reject_reason VARCHAR, "
                "dedup_key VARCHAR, jd_text VARCHAR)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO jobs (id, reject_reason, dedup_key, jd_text) VALUES "
                "(1, 'off-target role: trucking', NULL, 'jd one'), "
                "(2, 'salary below minimum', 'acme|eng', 'jd two'), "
                "(3, NULL, NULL, 'jd three')"
            )
        )
    return engine


def test_reject_category_backfills_from_reason():
    engine = _legacy_engine()
    ensure_reject_category_column(engine)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT id, reject_category FROM jobs")).mappings().all()
        rows = {int(row["id"]): row["reject_category"] for row in result}
    assert rows[1] == "relevance"
    assert rows[2] == "filtered"
    assert rows[3] is None


def test_content_fingerprint_backfills_all_rows():
    engine = _legacy_engine()
    ensure_content_fingerprint_column(engine)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT id, content_fingerprint FROM jobs")).mappings().all()
        rows = {int(row["id"]): row["content_fingerprint"] for row in result}
    assert all(rows[i] for i in (1, 2, 3))  # every non-blank jd_text got a fingerprint
