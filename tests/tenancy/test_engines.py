from sqlalchemy import inspect

from resume_agent.tenancy.engines import EngineRegistry


def test_registry_caches_per_user_and_evicts(tmp_path):
    registry = EngineRegistry()
    url = f"sqlite:///{(tmp_path / 'alice.db').as_posix()}"
    first = registry.get("alice", url)
    assert registry.get("alice", url) is first
    assert "jobs" in inspect(first).get_table_names()
    registry.evict("alice")
    assert registry.get("alice", url) is not first
    registry.close_all()


def test_registry_rejects_same_user_with_different_database(tmp_path):
    registry = EngineRegistry()
    registry.get("alice", f"sqlite:///{(tmp_path / 'one.db').as_posix()}")
    try:
        with __import__("pytest").raises(ValueError, match="different database"):
            registry.get("alice", f"sqlite:///{(tmp_path / 'two.db').as_posix()}")
    finally:
        registry.close_all()
