from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

from resume_tailor_harness.tenancy.context import current_context

logger = logging.getLogger(__name__)


class TenantPathError(ValueError):
    """A persisted path attempts to escape its tenant-owned storage root."""


@dataclass(frozen=True)
class StagedArtifactPdf:
    """A recoverable rename held until the owning database row commits."""

    original_path: Path
    staged_path: Path


def _confine(path: Path | str, root: Path, *, prefix: str | None = None) -> Path:
    root = root.resolve()
    candidate = Path(path)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        parts = candidate.parts
        if prefix is not None and parts and parts[0] == prefix:
            # Tenant-root-relative convention used by workspace-import
            # normalization (``account.py``): strip the leading marker and
            # join onto the confined root.
            resolved = root.joinpath(*parts[1:]).resolve()
        else:
            # A plain relative path -- e.g. a freshly rendered ``pdf_path``
            # when ``data_dir`` itself is configured relatively, in which
            # case ``root`` is also relative and both resolve against the
            # same process CWD.
            resolved = candidate.resolve()
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


def resolve_artifact_pdf(pdf_path: str | None) -> Path | None:
    """Resolve a stored ``pdf_path`` to a tenant-confined existing file, or None."""

    if not pdf_path:
        return None
    try:
        path = artifact_path(pdf_path)
    except TenantPathError:
        return None
    return path if path.is_file() else None


def delete_artifact_pdf(pdf_path: str | None) -> bool:
    """Unlink a stored artifact PDF, confined to the tenant's own output root.

    Returns True only when a file was actually removed. Every other outcome --
    no recorded path, a file already gone, a path that resolves outside the
    tenant root, an unlinkable file -- is reported as False rather than raised,
    because the caller is deleting the row that owns this path: letting an
    unusable path abort that would strand the row permanently, which is the
    opposite of the guarantee deletion exists to provide.
    """

    path = resolve_artifact_pdf(pdf_path)
    if path is None:
        return False
    try:
        path.unlink()
    except OSError:
        # Worth a record -- this is the one branch that leaves a real file
        # behind after its owning row is gone.
        logger.warning("could not unlink artifact %s", path, exc_info=True)
        return False
    return True


def stage_artifact_pdf(pdf_path: str | None) -> StagedArtifactPdf | None:
    """Atomically move an artifact aside so a failed row delete can restore it."""
    path = resolve_artifact_pdf(pdf_path)
    if path is None:
        return None
    staged = path.with_name(f".{path.name}.{uuid.uuid4().hex}.deleting")
    try:
        path.replace(staged)
    except OSError:
        logger.warning("could not stage artifact %s", path, exc_info=True)
        return None
    return StagedArtifactPdf(original_path=path, staged_path=staged)


def restore_staged_artifact_pdf(staged: StagedArtifactPdf) -> bool:
    """Put a staged artifact back after its database transaction rolls back."""
    try:
        staged.staged_path.replace(staged.original_path)
    except OSError:
        logger.warning(
            "could not restore staged artifact %s", staged.original_path, exc_info=True
        )
        return False
    return True


def delete_staged_artifact_pdf(staged: StagedArtifactPdf) -> bool:
    """Finalize deletion through the same tenant-confined unlink chokepoint."""
    return delete_artifact_pdf(str(staged.staged_path))
