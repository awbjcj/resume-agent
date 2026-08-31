"""Filesystem path confinement for names that may cross a trust boundary."""

from __future__ import annotations

import os
from pathlib import Path


class PathEscapeError(ValueError):
    """A candidate path resolved outside the root that owns it."""


def confined_path(root: Path | str, *parts: Path | str) -> Path:
    """Resolve a child path without permitting it to escape ``root``.

    Resolve both values before comparing so existing symlinks cannot redirect a
    trusted-looking relative path. The trailing separator is load-bearing:
    ``/workspace/a`` must not accept the sibling ``/workspace/another``.

    The explicit normalize-then-prefix check is also understood by CodeQL's
    path-injection analysis. ``Path.is_relative_to`` is equivalent for the
    runtime guard, but is not currently modeled as a sanitizer there.
    """

    resolved_root = os.path.realpath(os.fspath(root))
    resolved = os.path.realpath(
        os.path.join(resolved_root, *(os.fspath(part) for part in parts))
    )
    root_prefix = os.path.join(resolved_root, "")
    if not resolved.startswith(root_prefix):
        raise PathEscapeError("path escapes its owning directory")
    return Path(resolved)
