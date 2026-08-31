from __future__ import annotations

from pathlib import Path

from resume_tailor_harness.tenancy.context import current_context

# Canonical Workspace layout. Every artifact a service or adapter defaults to
# is named exactly once here, as the relative path resolve_tenant_path rebases
# into the active Workspace (or leaves CWD-relative in legacy single-user mode).
FACTS_PATH = "data/profile/facts.json"
SEARCH_PATH = "config/search.yaml"
CONNECTORS_PATH = "config/connectors.yaml"
REVIEW_PATH = "config/review.yaml"
REVIEW_DEEP_PATH = "config/review_deep.yaml"
TELEMETRY_PATH = "data/connector_runs.json"
SKILL_ALIASES_PATH = "data/skill_aliases.json"
AGENT_GUIDANCE_PATH = "config/agent_guidance.yaml"


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
    if any(
        candidate == base or candidate.is_relative_to(base)
        for base in mappings.values()
    ):
        return candidate
    head, separator, tail = normalized.partition("/")
    base = mappings.get(head)
    if base is None:
        return candidate
    return base / tail if separator else base
