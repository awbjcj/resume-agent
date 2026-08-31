import sqlite3
import tarfile
from contextlib import closing

import pytest

from resume_tailor_harness.services.backup import (
    InvalidArchiveError,
    UnsafeArchiveError,
    export_data_root,
    import_data_root,
    sqlite_snapshot,
    _extract_validated,
)


def _make_root(tmp_path, name="data"):
    root = tmp_path / name
    (root / "profile").mkdir(parents=True)
    (root / "profile" / "facts.json").write_text('{"facts": []}', encoding="utf-8")
    (root / ".env").write_text("KEY=value\n", encoding="utf-8")
    db = root / "resume_tailor_harness.db"
    with closing(sqlite3.connect(db)) as connection:
        connection.execute("CREATE TABLE job (id INTEGER PRIMARY KEY, title TEXT)")
        connection.execute("INSERT INTO job (title) VALUES ('Engineer')")
        connection.commit()
    return root, db


def test_sqlite_snapshot_and_export_are_wal_safe(tmp_path):
    root, db = _make_root(tmp_path)
    snapshot = tmp_path / "snapshot.db"
    sqlite_snapshot(db, snapshot)
    with closing(sqlite3.connect(snapshot)) as connection:
        assert connection.execute("SELECT title FROM job").fetchall() == [("Engineer",)]

    (root / "resume_tailor_harness.db-wal").write_bytes(b"")
    archive = export_data_root(root, f"sqlite:///{db.as_posix()}", tmp_path / "out")
    with tarfile.open(archive) as tar:
        names = tar.getnames()
    assert "profile/facts.json" in names
    assert "resume_tailor_harness.db" in names
    assert "resume_tailor_harness.db-wal" not in names


def test_import_roundtrip_full_replaces_root(tmp_path):
    root, db = _make_root(tmp_path)
    archive = export_data_root(root, f"sqlite:///{db.as_posix()}", tmp_path / "out")
    (root / "profile" / "facts.json").write_text("changed", encoding="utf-8")
    (root / "stray.txt").write_text("stray", encoding="utf-8")

    import_data_root(archive, root)

    assert (root / "profile" / "facts.json").read_text(
        encoding="utf-8"
    ) == '{"facts": []}'
    assert not (root / "stray.txt").exists()


def test_import_with_relative_data_root_does_not_move_rollback_into_itself(
    tmp_path, monkeypatch
):
    root, db = _make_root(tmp_path)
    archive = export_data_root(root, f"sqlite:///{db.as_posix()}", tmp_path / "out")
    (root / "stray.txt").write_text("stray", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    import_data_root(archive, root.relative_to(tmp_path))

    assert (root / "profile" / "facts.json").is_file()
    assert not (root / "stray.txt").exists()
    assert not list(root.glob(".ra-import-rollback-*"))


def test_import_rejects_traversal_and_empty_archives_before_touching_root(tmp_path):
    root, _ = _make_root(tmp_path)
    payload = tmp_path / "payload.txt"
    payload.write_text("bad", encoding="utf-8")
    evil = tmp_path / "evil.tar.gz"
    with tarfile.open(evil, "w:gz") as tar:
        tar.add(payload, arcname="../escape.txt")
    with pytest.raises(UnsafeArchiveError):
        import_data_root(evil, root)

    empty = tmp_path / "empty.tar.gz"
    with tarfile.open(empty, "w:gz"):
        pass
    with pytest.raises(InvalidArchiveError):
        import_data_root(empty, root)
    assert (root / "profile" / "facts.json").exists()


def test_archive_limits_are_checked_before_extraction(tmp_path):
    payload = tmp_path / "payload.txt"
    payload.write_bytes(b"12345")
    archive = tmp_path / "limited.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(payload, arcname="one.txt")
        tar.add(payload, arcname="two.txt")

    destination = tmp_path / "destination"
    destination.mkdir()
    with pytest.raises(InvalidArchiveError, match="more than 1"):
        _extract_validated(archive, destination, max_members=1)
    with pytest.raises(InvalidArchiveError, match="storage limit"):
        _extract_validated(archive, destination, max_expanded_bytes=9)
    assert list(destination.iterdir()) == []


def test_import_rolls_back_when_install_move_fails(tmp_path, monkeypatch):
    from resume_tailor_harness.services import backup

    root, db = _make_root(tmp_path)
    archive = export_data_root(root, f"sqlite:///{db.as_posix()}", tmp_path / "out")
    original_move = backup.shutil.move
    failed = False

    def flaky_move(source, destination):
        nonlocal failed
        source_path = backup.Path(source)
        if not failed and ".ra-import-stage-" in str(source_path.parent):
            failed = True
            raise OSError("injected install failure")
        return original_move(source, destination)

    monkeypatch.setattr(backup.shutil, "move", flaky_move)

    with pytest.raises(OSError, match="injected"):
        import_data_root(archive, root)
    assert (root / "profile" / "facts.json").exists()
    with closing(sqlite3.connect(root / "resume_tailor_harness.db")) as connection:
        assert connection.execute("SELECT title FROM job").fetchall() == [("Engineer",)]


def test_import_rolls_back_when_post_swap_validation_fails(tmp_path):
    root, db = _make_root(tmp_path)
    archive = export_data_root(root, f"sqlite:///{db.as_posix()}", tmp_path / "out")
    (root / "profile" / "facts.json").write_text("current", encoding="utf-8")

    def reject_replacement():
        raise RuntimeError("replacement database is invalid")

    with pytest.raises(RuntimeError, match="replacement database is invalid"):
        import_data_root(archive, root, after_swap=reject_replacement)

    assert (root / "profile" / "facts.json").read_text(encoding="utf-8") == "current"
    assert not list(root.glob(".ra-import-rollback-*"))


def test_import_preserves_rollback_directory_when_restore_also_fails(
    tmp_path, monkeypatch
):
    from resume_tailor_harness.services import backup

    root, db = _make_root(tmp_path)
    archive = export_data_root(root, f"sqlite:///{db.as_posix()}", tmp_path / "out")
    original_move = backup.shutil.move

    def doubly_flaky_move(source, destination):
        source_path = backup.Path(source)
        if ".ra-import-stage-" in str(source_path.parent):
            raise OSError("install failed")
        if (
            ".ra-import-rollback-" in str(source_path.parent)
            and source_path.name == "resume_tailor_harness.db"
        ):
            raise OSError("restore failed")
        return original_move(source, destination)

    monkeypatch.setattr(backup.shutil, "move", doubly_flaky_move)

    with pytest.raises(RuntimeError, match="rollback preserved"):
        import_data_root(archive, root)
    rollback_dirs = list(root.glob(".ra-import-rollback-*"))
    assert len(rollback_dirs) == 1
    assert (rollback_dirs[0] / "resume_tailor_harness.db").is_file()


def test_pack_local_checkout_builds_importable_volume_layout(tmp_path):
    from resume_tailor_harness.services.backup import pack_local_checkout

    repo = tmp_path / "repo"
    (repo / "data" / "profile").mkdir(parents=True)
    (repo / "data" / "profile" / "facts.json").write_text("{}", encoding="utf-8")
    db = repo / "data" / "resume_tailor_harness.db"
    with closing(sqlite3.connect(db)) as connection:
        connection.execute("CREATE TABLE job (id INTEGER PRIMARY KEY)")
        connection.commit()
    (repo / "config").mkdir()
    (repo / "config" / "search.yaml").write_text("titles: []\n", encoding="utf-8")
    (repo / "output").mkdir()
    (repo / "output" / "resume.pdf").write_bytes(b"%PDF")
    (repo / ".env").write_text("KEY=value\n", encoding="utf-8")

    archive = pack_local_checkout(repo, tmp_path / "seed.tar.gz")
    restored = tmp_path / "restored"
    import_data_root(archive, restored)

    assert (restored / "profile" / "facts.json").is_file()
    assert (restored / "resume_tailor_harness.db").is_file()
    assert (restored / "config" / "search.yaml").is_file()
    assert (restored / "output" / "resume.pdf").is_file()
    assert (restored / ".env").is_file()


def test_pack_local_checkout_rejects_empty_or_symlinked_state(tmp_path):
    from resume_tailor_harness.services.backup import pack_local_checkout

    repo = tmp_path / "repo"
    (repo / "data").mkdir(parents=True)
    with pytest.raises(InvalidArchiveError):
        pack_local_checkout(repo, tmp_path / "empty.tar.gz")

    target = tmp_path / "outside.txt"
    target.write_text("secret", encoding="utf-8")
    try:
        (repo / "data" / "link.txt").symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(UnsafeArchiveError):
        pack_local_checkout(repo, tmp_path / "unsafe.tar.gz")
