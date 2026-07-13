import shutil

import pytest

from resume_agent.tenancy import migrate


def _legacy_root(tmp_path):
    root = tmp_path / "data"
    (root / "profile").mkdir(parents=True)
    (root / "profile" / "facts.json").write_text("{}", encoding="utf-8")
    (root / "resume_agent.db").write_bytes(b"db")
    (root / ".env").write_text("GITHUB_TOKEN=token\n", encoding="utf-8")
    return root


def test_adoption_moves_legacy_children_and_env(tmp_path):
    root = _legacy_root(tmp_path)
    moved = migrate.adopt_legacy_root(root, "abc123def456")
    workspace = root / "users" / "abc123def456"
    assert set(moved) == {"resume_agent.db", "profile", ".env"}
    assert (workspace / "profile" / "facts.json").is_file()
    assert (workspace / "secrets.env").is_file()
    assert not (root / migrate.ADOPTION_JOURNAL).exists()


def test_adoption_replaces_empty_provisioned_workspace_directories(tmp_path):
    root = _legacy_root(tmp_path)
    (root / "config").mkdir()
    (root / "config" / "connectors.yaml").write_text("{}", encoding="utf-8")
    workspace = root / "users" / "abc123def456"
    (workspace / "config").mkdir(parents=True)

    migrate.adopt_legacy_root(root, "abc123def456")

    assert (workspace / "config" / "connectors.yaml").is_file()
    assert not (root / "config").exists()


def test_migrated_root_ignores_recreated_compatibility_paths(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    (root / "system.db").write_bytes(b"system")
    (root / "config").mkdir()
    (root / "output").mkdir()
    (root / ".env").touch()

    assert migrate.is_legacy_root(root) is False

    (root / "resume_agent.db").write_bytes(b"legacy")
    assert migrate.is_legacy_root(root) is True


def test_adoption_rolls_back_completed_moves_on_failure(tmp_path, monkeypatch):
    root = _legacy_root(tmp_path)
    real_move = shutil.move
    calls = 0

    def fail_second(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("disk failure")
        return real_move(source, target)

    monkeypatch.setattr(migrate.shutil, "move", fail_second)
    with pytest.raises(migrate.AdoptionError, match="rolled back"):
        migrate.adopt_legacy_root(root, "abc123def456")
    assert (root / "resume_agent.db").is_file()
    assert (root / "profile").is_dir()
