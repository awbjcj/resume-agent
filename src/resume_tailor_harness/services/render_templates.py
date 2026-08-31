"""Validate, store, preview, and delete tenant-owned Typst templates."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from resume_tailor_harness.render.renderer import render_pdf
from resume_tailor_harness.render.sample_content import sample_resume_content
from resume_tailor_harness.render.templates import (
    CUSTOM_TEMPLATES_DIR,
    TemplateInfo,
    TemplateNotFoundError,
    custom_template_path,
    resolve_template,
    validate_custom_stem,
)
from resume_tailor_harness.tenancy.paths import resolve_tenant_path


MAX_TEMPLATE_BYTES = 200 * 1024


class TemplateValidationError(ValueError):
    """A candidate template cannot safely compile against the sample resume."""


def validate_template(path: Path) -> None:
    try:
        with tempfile.TemporaryDirectory() as output_directory:
            render_pdf(
                sample_resume_content(),
                Path(output_directory) / "probe.pdf",
                path,
                fit_pages=None,
                root=path.parent,
            )
    except Exception as exc:
        raise TemplateValidationError(str(exc)) from exc


def _stem_from_filename(filename: str) -> str:
    if not filename.endswith(".typ") or filename.count(".") != 1:
        raise TemplateValidationError(
            "Upload one .typ file named with letters, digits, hyphens, or underscores."
        )
    try:
        return validate_custom_stem(filename.removesuffix(".typ"))
    except TemplateNotFoundError as exc:
        raise TemplateValidationError(str(exc)) from exc


def save_custom_template(filename: str, data: bytes) -> TemplateInfo:
    stem = _stem_from_filename(filename)
    if len(data) > MAX_TEMPLATE_BYTES:
        raise TemplateValidationError("Template exceeds the 200 KB limit.")

    target_directory = resolve_tenant_path(CUSTOM_TEMPLATES_DIR).resolve()
    target_directory.mkdir(parents=True, exist_ok=True)
    target = custom_template_path(stem)
    candidate: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=target_directory,
            prefix=f".{stem}.",
            suffix=".typ",
            delete=False,
        ) as temporary:
            candidate = temporary.name
            temporary.write(data)
        validate_template(Path(candidate))
        os.replace(candidate, target)
        candidate = None
    finally:
        if candidate is not None:
            try:
                os.unlink(candidate)
            except FileNotFoundError:
                pass
    return resolve_template(f"custom:{stem}")


def delete_custom_template(stem: str, store) -> bool:
    path = custom_template_path(stem)
    if not path.is_file():
        return False
    render_doc = store.get("render")
    if render_doc.template == f"custom:{stem}":
        store.put("render", render_doc.model_copy(update={"template": "classic"}))
    path.unlink()
    return True


def clear_custom_render_template(store) -> None:
    """Fall back to classic when the active template is a custom upload.

    The templates-section reset removes every custom ``.typ`` at once, so
    ``render.yaml`` must not keep naming one -- the same reconciliation
    ``delete_custom_template`` performs for a single stem. Bundled ids and the
    empty default are left untouched.
    """
    render_doc = store.get("render")
    if render_doc.template and render_doc.template.startswith("custom:"):
        store.put("render", render_doc.model_copy(update={"template": "classic"}))


def render_preview(template_id: str) -> bytes:
    info = resolve_template(template_id)
    try:
        with tempfile.TemporaryDirectory() as output_directory:
            output = render_pdf(
                sample_resume_content(),
                Path(output_directory) / "preview.pdf",
                info.path,
                fit_pages=None,
                root=info.path.parent,
            )
            return output.read_bytes()
    except Exception as exc:
        raise TemplateValidationError(str(exc)) from exc
