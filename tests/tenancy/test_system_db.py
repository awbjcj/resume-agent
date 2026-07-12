from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from resume_agent.db import init_db, make_engine
from resume_agent.tenancy.system_db import (
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
