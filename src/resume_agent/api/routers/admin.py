"""Authenticated whole-root backup and destructive restore endpoints."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Request, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from resume_agent.api.deps import refresh_app_settings
from resume_agent.api.errors import ApiException
from resume_agent.config import Settings
from resume_agent.db import init_db, make_engine
from resume_agent.services.backup import (
    InvalidArchiveError,
    UnsafeArchiveError,
    export_data_root,
    import_data_root,
)

router = APIRouter(prefix="/admin", tags=["admin"])


def _refuse_if_running(request: Request) -> None:
    if request.app.state.run_manager.list_active():
        raise ApiException(409, "RUNS_ACTIVE", "Refusing while runs are active")


@router.get("/export")
def export_root(request: Request) -> FileResponse:
    _refuse_if_running(request)
    temporary = Path(tempfile.mkdtemp(prefix="ra-export-"))
    try:
        archive = export_data_root(
            request.app.state.data_dir,
            request.app.state.db_url,
            temporary,
        )
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return FileResponse(
        archive,
        media_type="application/gzip",
        filename=archive.name,
        background=BackgroundTask(shutil.rmtree, temporary, ignore_errors=True),
    )


@router.post("/import")
def import_root(
    request: Request,
    file: UploadFile,
    confirm: str = "",
) -> dict[str, str]:
    if confirm != "REPLACE":
        raise ApiException(
            400,
            "CONFIRM_REQUIRED",
            "Import replaces the data root; pass ?confirm=REPLACE",
        )
    _refuse_if_running(request)
    with tempfile.TemporaryDirectory() as temporary:
        archive = Path(temporary) / "import.tar.gz"
        with archive.open("wb") as destination:
            shutil.copyfileobj(file.file, destination)
        try:
            import_data_root(
                archive,
                request.app.state.data_dir,
                before_swap=request.app.state.engine.dispose,
            )
        except UnsafeArchiveError as exc:
            raise ApiException(400, "UNSAFE_ARCHIVE", str(exc)) from exc
        except InvalidArchiveError as exc:
            raise ApiException(400, "INVALID_ARCHIVE", str(exc)) from exc
        finally:
            engine = make_engine(request.app.state.db_url)
            init_db(engine)
            request.app.state.engine = engine
    refresh_app_settings(
        request.app,
        Settings(_env_file=request.app.state.env_path),  # type: ignore[call-arg]
    )
    return {"status": "imported"}
