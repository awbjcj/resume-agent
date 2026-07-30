from __future__ import annotations

from pathlib import Path

from resume_agent.tenancy.context import current_context


class TenantPathError(ValueError):
    """A persisted path attempts to escape its tenant-owned storage root."""


def _confine(path: Path | str, root: Path, *, prefix: str | None = None) -> Path:
    root = root.resolve()
    candidate = Path(path)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        parts = candidate.parts
        if prefix is not None and parts and parts[0] == prefix:
            parts = parts[1:]
        resolved = root.joinpath(*parts).resolve()
    if not resolved.is_relative_to(root):
        raise TenantPathError(f"path is outside the tenant {root.name} root")
    return resolved


def artifact_path(path: Path | str) -> Path:
    """Resolve a rendered artifact without permitting cross-workspace reads.

    Local/single-user mode intentionally retains its historical explicit-path
    behavior. Multi-user requests always resolve beneath the active tenant's
    output directory, including paths restored from older workspace backups.
    """

    context = current_context()
    if context is None:
        return Path(path)
    return _confine(path, context.paths.output_dir, prefix="output")
