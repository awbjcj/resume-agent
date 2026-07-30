from sqlalchemy import inspect, select, text
from sqlalchemy.orm import Session

from resume_agent.db import init_db, make_engine
from resume_agent.tenancy.system_db import (
    UsageEvent,
    User,
    init_system_db,
    make_system_engine,
)


def test_system_metadata_is_isolated_from_workspace_metadata(tmp_path):
    system_engine = make_system_engine(tmp_path / "data")
    workspace_engine = make_engine(
        f"sqlite:///{(tmp_path / 'workspace.db').as_posix()}"
    )
    init_system_db(system_engine)
    init_db(workspace_engine)
    assert "users" in inspect(system_engine).get_table_names()
    assert "job" not in inspect(system_engine).get_table_names()
    assert "users" not in inspect(workspace_engine).get_table_names()
    system_engine.dispose()
    workspace_engine.dispose()


def test_user_roundtrip_includes_limits_and_last_activity(tmp_path):
    engine = make_system_engine(tmp_path)
    init_system_db(engine)
    with Session(engine) as session:
        session.add(
            User(
                id="abc123def456", username="alice", password_hash="hash", role="admin"
            )
        )
        session.commit()
    with Session(engine) as session:
        user = session.execute(select(User)).scalar_one()
        assert user.weekly_token_budget is None
        assert user.last_active_at is None
    engine.dispose()


def test_legacy_usage_migration_preserves_tokens_without_inventing_cost(tmp_path):
    engine = make_system_engine(tmp_path)
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE users (id VARCHAR(12) PRIMARY KEY, username VARCHAR(64), password_hash VARCHAR, role VARCHAR(8))"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE usage_events (id INTEGER PRIMARY KEY, user_id VARCHAR(12), ts DATETIME, provider VARCHAR(32), model VARCHAR(160), input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0, cache_read_tokens INTEGER DEFAULT 0, cache_creation_tokens INTEGER DEFAULT 0, weighted_total FLOAT DEFAULT 0, own_key BOOLEAN DEFAULT 0)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO usage_events (id, user_id, input_tokens, output_tokens, cache_creation_tokens) VALUES (1, 'abc123def456', 100, 20, 5)"
            )
        )

    init_system_db(engine)

    with Session(engine) as session:
        event = session.get(UsageEvent, 1)
        assert event is not None
        assert event.total_tokens == 120
        assert event.cache_write_tokens == 5
        assert event.cost_micros is None
        assert event.pricing_status == "LEGACY_UNPRICED"
    engine.dispose()
