"""The two global aggregates must not full-scan ``usage_events``.

`usage_events` grows one row per LLM call, forever. `global_monthly_cost` and
`global_weekly_usage` filter on ``own_key`` + ``ts`` with no ``user_id``
predicate, so neither the ``(user_id, ts)`` index nor the bare ``user_id``
index applied and both queries degraded into a full scan that got slower every
week the platform ran.

Asserting on the *plan* rather than on a timing is deliberate: a scan is a
scan whether or not the table happens to be small on a CI box today.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from resume_tailor_harness.tenancy.system_db import init_system_db, make_system_engine

NOW = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)

_GLOBAL_MONTHLY_COST = """
SELECT coalesce(sum(cost_micros), 0) FROM usage_events
WHERE own_key IS 0 AND ts >= :start AND cost_micros IS NOT NULL
"""

_GLOBAL_WEEKLY_USAGE = """
SELECT coalesce(sum(weighted_total), 0.0) FROM usage_events
WHERE own_key IS 0 AND ts >= :start
"""


def _plan(engine, sql: str) -> str:
    with Session(engine) as session:
        rows = session.execute(
            text(f"EXPLAIN QUERY PLAN {sql}"), {"start": NOW}
        ).fetchall()
    return " | ".join(str(row[-1]) for row in rows)


def test_global_aggregates_use_the_own_key_index(tmp_path):
    engine = make_system_engine(tmp_path)
    init_system_db(engine)

    for sql in (_GLOBAL_MONTHLY_COST, _GLOBAL_WEEKLY_USAGE):
        plan = _plan(engine, sql)
        assert "SCAN usage_events" not in plan, plan
        assert "ix_usage_events_own_key_ts" in plan, plan


def test_migration_adds_the_index_to_an_existing_database(tmp_path):
    """A deployment that predates the index gets it without a manual step."""
    engine = make_system_engine(tmp_path)
    init_system_db(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP INDEX ix_usage_events_own_key_ts"))

    from resume_tailor_harness.tenancy.migrate_system import migrate_system_db

    migrate_system_db(engine)

    plan = _plan(engine, _GLOBAL_MONTHLY_COST)
    assert "ix_usage_events_own_key_ts" in plan, plan
