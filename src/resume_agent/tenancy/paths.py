from __future__ import annotations

from pathlib import Path

from resume_agent.tenancy.context import current_context


def resolve_tenant_path(path: Path | str) -> Path:
    """Rebase historical mutable defaults into the active Workspace."""
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    context = current_context()
    if context is None:
        return candidate
    normalized = candidate.as_posix()
    mappings = {
        "data": context.paths.root,
        "config": context.paths.config_dir,
        "output": context.paths.output_dir,
    }
    if any(candidate == base or candidate.is_relative_to(base) for base in mappings.values()):
        return candidate
    head, separator, tail = normalized.partition("/")
    base = mappings.get(head)
    if base is None:
        return candidate
    return base / tail if separator else base
