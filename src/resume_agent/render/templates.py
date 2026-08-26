"""Resolve public template identifiers to trusted filesystem paths."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from resume_agent.security.paths import confined_path
from resume_agent.tenancy.context import current_context
from resume_agent.tenancy.paths import resolve_tenant_path


CUSTOM_TEMPLATES_DIR = "config/templates"
_CUSTOM_STEM = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class TemplateInfo:
    id: str
    title: str
    description: str
    kind: str
    path: Path


BUNDLED = {
    "classic": TemplateInfo(
        id="classic",
        title="Classic",
        description="Compact single-column resume with clear section hierarchy.",
        kind="bundled",
        path=_REPOSITORY_ROOT / "templates" / "resume.typ",
    )
}


class TemplateNotFoundError(ValueError):
    """The public template id does not resolve to an available template."""


def validate_custom_stem(stem: str) -> str:
    if not _CUSTOM_STEM.fullmatch(stem):
        raise TemplateNotFoundError(
            "Custom template names may contain letters, digits, hyphens, and underscores."
        )
    return stem


def custom_template_path(stem: str) -> Path:
    safe_stem = validate_custom_stem(stem)
    directory = resolve_tenant_path(CUSTOM_TEMPLATES_DIR).resolve()
    try:
        return confined_path(directory, f"{safe_stem}.typ")
    except ValueError as exc:
        raise TemplateNotFoundError("Custom template path escapes the workspace.") from exc


def _custom_info(stem: str, path: Path) -> TemplateInfo:
    return TemplateInfo(
        id=f"custom:{stem}",
        title=stem,
        description="Uploaded template",
        kind="custom",
        path=path,
    )


def resolve_template(template_id: str) -> TemplateInfo:
    bundled = BUNDLED.get(template_id)
    if bundled is not None:
        return bundled
    if template_id.startswith("custom:"):
        stem = template_id.removeprefix("custom:")
        path = custom_template_path(stem)
        if path.is_file():
            return _custom_info(stem, path)
    raise TemplateNotFoundError(
        f"Template {template_id!r} does not exist. Pick a bundled template or "
        "re-upload the custom file."
    )


def list_templates() -> list[TemplateInfo]:
    directory = resolve_tenant_path(CUSTOM_TEMPLATES_DIR)
    custom_paths = sorted(directory.glob("*.typ"), key=lambda path: path.stem)
    custom = [
        _custom_info(path.stem, path)
        for path in custom_paths
        if _CUSTOM_STEM.fullmatch(path.stem)
    ]
    return [*BUNDLED.values(), *custom]


def template_path_for(config) -> Path:
    """Resolve new template ids while retaining the legacy CLI path escape hatch."""
    if config.template:
        return resolve_template(config.template).path
    if config.template_path:
        if current_context() is not None:
            if Path(config.template_path).as_posix() == "templates/resume.typ":
                return resolve_template("classic").path
            raise TemplateNotFoundError(
                "Legacy template paths are disabled in multi-user mode; use a template id."
            )
        return Path(config.template_path)
    return resolve_template("classic").path
