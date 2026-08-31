"""Settings transfer and reset. Storage lives behind settings_sections."""

from __future__ import annotations

import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from resume_tailor_harness.api.deps import get_config_store
from resume_tailor_harness.api.errors import ApiException
from resume_tailor_harness.api.schemas.settings import (
    BundleApplied,
    BundlePreview,
    SettingsSectionList,
    SettingsSectionOut,
)
from resume_tailor_harness.api.uploads import UploadTooLargeError, copy_upload
from resume_tailor_harness.services.backup import UnsafeArchiveError
from resume_tailor_harness.services.render_templates import clear_custom_render_template
from resume_tailor_harness.services.settings_bundle import (
    InvalidBundleError,
    UnsupportedBundleVersionError,
    export_settings_bundle,
    import_settings_bundle,
    read_bundle_manifest,
)
from resume_tailor_harness.settings_sections import (
    SECTIONS_BY_ID,
    SETTINGS_SECTIONS,
    SettingsSection,
    is_customized,
    reset_section,
    section_for,
)
from resume_tailor_harness.tenancy.context import current_context

router = APIRouter(prefix="/settings", tags=["settings"])
link_router = APIRouter(prefix="/settings", tags=["settings"])

_MAX_BUNDLE_BYTES = 8 * 1024 * 1024


def _out(section: SettingsSection) -> SettingsSectionOut:
    return SettingsSectionOut(
        id=section.id, label=section.label, customized=is_customized(section)
    )


def _staged_upload(file: UploadFile, temporary: str) -> Path:
    archive = Path(temporary) / "bundle.tar.gz"
    try:
        copy_upload(file, archive, max_bytes=_MAX_BUNDLE_BYTES)
    except UploadTooLargeError as exc:
        raise ApiException(413, "UPLOAD_TOO_LARGE", str(exc)) from exc
    return archive


def _bundle_error(exc: Exception) -> ApiException:
    if isinstance(exc, UnsupportedBundleVersionError):
        return ApiException(400, "UNSUPPORTED_VERSION", str(exc))
    if isinstance(exc, UnsafeArchiveError):
        return ApiException(400, "UNSAFE_ARCHIVE", str(exc))
    return ApiException(400, "INVALID_BUNDLE", str(exc))


@router.get("/sections", response_model=SettingsSectionList)
def list_sections() -> SettingsSectionList:
    return SettingsSectionList(sections=[_out(s) for s in SETTINGS_SECTIONS])


@link_router.get("/bundle")
def export_bundle() -> FileResponse:
    temporary = Path(tempfile.mkdtemp(prefix="ra-settings-export-"))
    try:
        archive = export_settings_bundle(temporary)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return FileResponse(
        archive,
        media_type="application/gzip",
        filename=f"resume-tailor-harness-settings-{datetime.now(UTC).date().isoformat()}.tar.gz",
        background=BackgroundTask(shutil.rmtree, temporary, ignore_errors=True),
    )


@router.post("/bundle/preview", response_model=BundlePreview)
def preview_bundle(file: UploadFile) -> BundlePreview:
    with tempfile.TemporaryDirectory(prefix="ra-settings-preview-") as temporary:
        archive = _staged_upload(file, temporary)
        try:
            manifest = read_bundle_manifest(archive)
        except (InvalidBundleError, UnsafeArchiveError) as exc:
            raise _bundle_error(exc) from exc
    return BundlePreview(
        version=manifest.version,
        exported_at=manifest.exported_at,
        sections=[_out(SECTIONS_BY_ID[i]) for i in manifest.sections],
        unknown_sections=list(manifest.unknown_sections),
    )


@router.post("/bundle", response_model=BundleApplied)
def apply_bundle(
    request: Request, file: UploadFile, confirm: str = ""
) -> BundleApplied:
    if confirm != "APPLY":
        raise ApiException(
            400,
            "CONFIRM_REQUIRED",
            "Importing replaces the settings a bundle names; pass ?confirm=APPLY",
        )
    context = current_context()
    user_id = context.user_id if context is not None else None
    if request.app.state.run_manager.list_active(user_id=user_id):
        raise ApiException(409, "RUNS_ACTIVE", "Refusing while your runs are active")
    with tempfile.TemporaryDirectory(prefix="ra-settings-import-") as temporary:
        archive = _staged_upload(file, temporary)
        try:
            applied = import_settings_bundle(archive)
        except (InvalidBundleError, UnsafeArchiveError) as exc:
            raise _bundle_error(exc) from exc
    return BundleApplied(applied=list(applied))


@router.post("/sections/{section_id}/reset", response_model=SettingsSectionOut)
def reset(section_id: str, request: Request) -> SettingsSectionOut:
    section = section_for(section_id)
    if section is None:
        raise ApiException(404, "NOT_FOUND", f"No settings section {section_id!r}")
    context = current_context()
    user_id = context.user_id if context is not None else None
    if request.app.state.run_manager.list_active(user_id=user_id):
        raise ApiException(409, "RUNS_ACTIVE", "Refusing while your runs are active")
    reset_section(section)
    # Removing every custom template would leave render.yaml naming one that no
    # longer exists; rendering never silently falls back, so reconcile here.
    if section.id == "templates":
        clear_custom_render_template(get_config_store(request))
    return _out(section)
