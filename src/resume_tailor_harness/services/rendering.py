"""Render use-case: load render config, render one resume version to PDF."""

from __future__ import annotations

from pathlib import Path

from sqlmodel import Session

from resume_tailor_harness.render.render_config import RenderConfig, load_render_config
from resume_tailor_harness.render.service import render_version

DEFAULT_RENDER = "config/render.yaml"


def _load_config(path: str) -> RenderConfig:
    from resume_tailor_harness.tenancy.paths import resolve_tenant_path

    resolved = resolve_tenant_path(path)
    return load_render_config(resolved) if resolved.exists() else RenderConfig()


def render_resume_version(
    session: Session, version_id: int, *, render_path: str = DEFAULT_RENDER
) -> Path | None:
    """Render a stored version to PDF; None if the version does not exist."""
    return render_version(session, version_id, _load_config(render_path))
