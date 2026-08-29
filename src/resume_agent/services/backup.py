"""Validated, WAL-safe whole-root export and rollback-safe import."""

from __future__ import annotations

import shutil
import sqlite3
import tarfile
import tempfile
from collections.abc import Callable
from contextlib import closing
from datetime import date
from pathlib import Path, PurePosixPath, PureWindowsPath


class UnsafeArchiveError(ValueError):
    """An archive member escapes the root or uses an unsupported type."""


class InvalidArchiveError(ValueError):
    """The upload is not a readable, non-empty data-root archive."""


DEFAULT_MAX_ARCHIVE_MEMBERS = 10_000
DEFAULT_MAX_ARCHIVE_EXPANDED_BYTES = 2 * 1024 * 1024 * 1024
DEFAULT_MAX_ARCHIVE_MEMBER_BYTES = 512 * 1024 * 1024
DEFAULT_MAX_COMPRESSION_RATIO = 200


def sqlite_snapshot(db_file: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with (
        closing(sqlite3.connect(db_file)) as source,
        closing(sqlite3.connect(destination)) as target,
    ):
        source.backup(target)


def _sqlite_file(db_url: str, data_root: Path) -> Path | None:
    prefix = "sqlite:///"
    if not db_url.startswith(prefix) or db_url.endswith(":memory:"):
        return None
    db_file = Path(db_url[len(prefix) :]).resolve()
    return db_file if db_file.is_relative_to(data_root.resolve()) else None


def _is_db_artifact(path: Path, db_file: Path) -> bool:
    return path.parent.resolve() == db_file.parent.resolve() and path.name in {
        db_file.name,
        f"{db_file.name}-wal",
        f"{db_file.name}-shm",
    }


def export_data_root(data_root: Path, db_url: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / f"resume-agent-data-{date.today().isoformat()}.tar.gz"
    configured_db = _sqlite_file(db_url, data_root)
    db_files = {path.resolve() for path in data_root.rglob("*.db") if path.is_file()}
    if configured_db is not None and configured_db.is_file():
        db_files.add(configured_db.resolve())
    with tempfile.TemporaryDirectory() as temporary:
        snapshots: list[tuple[Path, Path]] = []
        for index, db_file in enumerate(sorted(db_files)):
            snapshot = Path(temporary) / f"{index}-{db_file.name}"
            sqlite_snapshot(db_file, snapshot)
            snapshots.append((db_file, snapshot))
        with tarfile.open(archive, "w:gz") as tar:
            for path in sorted(data_root.rglob("*")):
                if path.is_symlink():
                    raise UnsafeArchiveError(f"data root contains a symlink: {path}")
                if not (path.is_file() or path.is_dir()):
                    raise UnsafeArchiveError(f"unsupported data-root entry: {path}")
                if any(_is_db_artifact(path, db_file) for db_file in db_files):
                    continue
                tar.add(
                    path,
                    arcname=path.relative_to(data_root).as_posix(),
                    recursive=False,
                )
            for db_file, snapshot in snapshots:
                tar.add(
                    snapshot,
                    arcname=db_file.relative_to(data_root.resolve()).as_posix(),
                )
    return archive


def _validate_member(member: tarfile.TarInfo) -> None:
    posix = PurePosixPath(member.name)
    windows = PureWindowsPath(member.name)
    if (
        not member.name
        or posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or ".." in posix.parts
        or ".." in windows.parts
    ):
        raise UnsafeArchiveError(f"unsafe path in archive: {member.name}")
    if not (member.isfile() or member.isdir()):
        raise UnsafeArchiveError(f"unsupported member type: {member.name}")


def _extract_validated(
    archive: Path,
    destination: Path,
    *,
    max_members: int = DEFAULT_MAX_ARCHIVE_MEMBERS,
    max_expanded_bytes: int = DEFAULT_MAX_ARCHIVE_EXPANDED_BYTES,
    max_member_bytes: int = DEFAULT_MAX_ARCHIVE_MEMBER_BYTES,
    max_compression_ratio: int = DEFAULT_MAX_COMPRESSION_RATIO,
) -> None:
    try:
        with tarfile.open(archive, "r:gz") as tar:
            members: list[tarfile.TarInfo] = []
            names: set[str] = set()
            expanded_bytes = 0
            for member in tar:
                if len(members) >= max_members:
                    raise InvalidArchiveError(
                        f"archive contains more than {max_members:,} members"
                    )
                _validate_member(member)
                if member.name in names:
                    raise InvalidArchiveError("archive contains duplicate paths")
                names.add(member.name)
                if member.isfile():
                    if member.size < 0:
                        raise InvalidArchiveError(
                            "archive contains an oversized member"
                        )
                    expanded_bytes += member.size
                    if expanded_bytes > max_expanded_bytes:
                        raise InvalidArchiveError(
                            "archive expands beyond the configured storage limit"
                        )
                    if member.size > max_member_bytes:
                        raise InvalidArchiveError(
                            "archive contains an oversized member"
                        )
                members.append(member)
            if not any(member.isfile() for member in members):
                raise InvalidArchiveError("archive contains no files")
            compressed_bytes = max(archive.stat().st_size, 1)
            if (
                expanded_bytes > 10 * 1024 * 1024
                and expanded_bytes > compressed_bytes * max_compression_ratio
            ):
                raise InvalidArchiveError("archive compression ratio is unsafe")
            tar.extractall(destination, members=members, filter="data")
    except (tarfile.ReadError, EOFError) as exc:
        raise InvalidArchiveError("upload is not a readable tar.gz archive") from exc


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def import_data_root(
    archive: Path,
    data_root: Path,
    *,
    validate_staged: Callable[[Path], None] | None = None,
    before_swap: Callable[[], None] | None = None,
    after_swap: Callable[[], None] | None = None,
    max_members: int = DEFAULT_MAX_ARCHIVE_MEMBERS,
    max_expanded_bytes: int = DEFAULT_MAX_ARCHIVE_EXPANDED_BYTES,
    max_member_bytes: int = DEFAULT_MAX_ARCHIVE_MEMBER_BYTES,
) -> None:
    """Stage and replace the root, retaining rollback until validation succeeds."""
    data_root = data_root.resolve()
    data_root.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".ra-import-stage-", dir=data_root))
    rollback = Path(tempfile.mkdtemp(prefix=".ra-import-rollback-", dir=data_root))
    preserve_rollback = False
    try:
        _extract_validated(
            archive,
            stage,
            max_members=max_members,
            max_expanded_bytes=max_expanded_bytes,
            max_member_bytes=max_member_bytes,
        )
        if validate_staged is not None:
            validate_staged(stage)
        if before_swap is not None:
            before_swap()
        live = [
            child for child in data_root.iterdir() if child not in {stage, rollback}
        ]
        installed: list[Path] = []
        try:
            for child in live:
                shutil.move(child, rollback / child.name)
            for child in list(stage.iterdir()):
                destination = data_root / child.name
                shutil.move(child, destination)
                installed.append(destination)
            if after_swap is not None:
                after_swap()
        except BaseException as swap_error:
            for child in reversed(installed):
                _remove(child)
            restore_errors: list[BaseException] = []
            for child in list(rollback.iterdir()):
                try:
                    shutil.move(child, data_root / child.name)
                except BaseException as restore_error:
                    restore_errors.append(restore_error)
            if restore_errors:
                preserve_rollback = True
                raise RuntimeError(
                    "import failed and rollback could not complete; "
                    f"rollback preserved at {rollback}"
                ) from swap_error
            raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        if not preserve_rollback:
            shutil.rmtree(rollback, ignore_errors=True)


def pack_local_checkout(repo_root: Path, out: Path) -> Path:
    """Pack local mutable paths into the same layout as the mounted data root."""
    out.parent.mkdir(parents=True, exist_ok=True)
    file_count = 0

    def add_tree(
        tar: tarfile.TarFile,
        root: Path,
        prefix: str,
        snapshot_dir: Path,
        *,
        snapshot_databases: bool,
    ) -> None:
        nonlocal file_count
        for index, path in enumerate(sorted(root.rglob("*"))):
            relative = path.relative_to(root).as_posix()
            archive_name = f"{prefix}/{relative}" if prefix else relative
            if path.is_symlink():
                raise UnsafeArchiveError(f"local state contains a symlink: {path}")
            if path.is_dir():
                tar.add(path, arcname=archive_name, recursive=False)
                continue
            if not path.is_file():
                raise UnsafeArchiveError(f"unsupported local state entry: {path}")
            if snapshot_databases and path.name.endswith((".db-wal", ".db-shm")):
                continue
            if snapshot_databases and path.suffix == ".db":
                snapshot = snapshot_dir / f"snapshot-{index}.db"
                sqlite_snapshot(path, snapshot)
                tar.add(snapshot, arcname=archive_name)
            else:
                tar.add(path, arcname=archive_name)
            file_count += 1

    try:
        with (
            tempfile.TemporaryDirectory() as temporary,
            tarfile.open(out, "w:gz") as tar,
        ):
            snapshot_dir = Path(temporary)
            data_dir = repo_root / "data"
            if data_dir.is_dir():
                add_tree(
                    tar,
                    data_dir,
                    "",
                    snapshot_dir,
                    snapshot_databases=True,
                )
            for name in ("config", "output"):
                root = repo_root / name
                if root.is_dir():
                    tar.add(root, arcname=name, recursive=False)
                    add_tree(
                        tar,
                        root,
                        name,
                        snapshot_dir,
                        snapshot_databases=False,
                    )
            env_file = repo_root / ".env"
            if env_file.is_symlink():
                raise UnsafeArchiveError(f"local state contains a symlink: {env_file}")
            if env_file.is_file():
                tar.add(env_file, arcname=".env")
                file_count += 1
        if file_count == 0:
            raise InvalidArchiveError("local checkout contains no mutable files")
    except BaseException:
        out.unlink(missing_ok=True)
        raise
    return out
