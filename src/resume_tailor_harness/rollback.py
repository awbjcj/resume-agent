"""Publish several files as one unit, or leave every one of them untouched.

Two subsystems commit more than one artifact per operation: taxonomy custody
writes the cluster map, the corrections ledger and the state sidecar together,
and a profile build publishes ``facts.json`` alongside the matrix derived from
it. Neither can tolerate a half-applied commit, because the surviving half
then describes data that no longer exists.

This is exception rollback, not crash atomicity: a process killed mid-commit
still leaves the artifacts torn, and closing that window needs a two-phase
write the individual savers do not offer today.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path


def restore_file(path: Path, payload: bytes | None) -> None:
    """Put one artifact back exactly as it was, via an atomic sibling replace."""

    if payload is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            delete=False,
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".rollback",
        ) as handle:
            temporary = Path(handle.name)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def rollback_scope(paths: Sequence[Path]) -> Iterator[None]:
    """Restore every named path if the body raises.

    A restore that cannot land must not mask the failure that triggered the
    rollback, and must not abandon the artifacts queued behind it. So every
    path is attempted, whatever could not be put back is named on the original
    exception, and that original exception is what propagates.
    """

    before = {path: path.read_bytes() if path.exists() else None for path in paths}
    try:
        yield
    except BaseException as error:
        unrestored: list[str] = []
        for path, payload in before.items():
            try:
                restore_file(path, payload)
            except OSError:
                unrestored.append(str(path))
        if unrestored:
            error.add_note("rollback could not restore: " + ", ".join(unrestored))
        raise
