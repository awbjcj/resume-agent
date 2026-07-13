"""Authenticated whole-root backup and destructive restore endpoints."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, Request, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from resume_agent.api.deps import refresh_app_settings, require_admin
from resume_agent.api.errors import ApiException
from resume_agent.config import Settings, env_settings
from resume_agent.db import init_db, make_engine
from resume_agent.services.backup import (
    InvalidArchiveError,
    UnsafeArchiveError,
    export_data_root,
    import_data_root,
)


def _require_admin_when_multiuser(request: Request) -> None:
    if getattr(request.app.state, "system_engine", None) is not None:
        require_admin()


router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(_require_admin_when_multiuser)],
)


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
        was_multiuser = request.app.state.system_engine is not None
        runtime_disposed = False

        def dispose_all() -> None:
            nonlocal runtime_disposed
            registry = request.app.state.engine_registry
            if registry is not None:
                registry.close_all()
            if request.app.state.system_engine is not None:
                request.app.state.system_engine.dispose()
            if not was_multiuser and request.app.state.engine is not None:
                request.app.state.engine.dispose()
            runtime_disposed = True

        def rebuild_runtime() -> None:
            nonlocal runtime_disposed
            if was_multiuser:
                from resume_agent.tenancy.bootstrap import (
                    build_context,
                    ensure_bootstrapped,
                )
                from resume_agent.tenancy.engines import EngineRegistry
                from resume_agent.tenancy.system_db import (
                    init_system_db,
                    make_system_engine,
                )

                system_engine = make_system_engine(request.app.state.data_dir)
                registry = EngineRegistry()
                try:
                    init_system_db(system_engine)
                    admin = ensure_bootstrapped(
                        request.app.state.data_dir,
                        system_engine,
                        request.app.state.settings,
                    )
                    context = build_context(
                        admin,
                        request.app.state.data_dir,
                        request.app.state.settings,
                        registry,
                        system_engine=system_engine,
                        template_dir=request.app.state.template_config_dir,
                    )
                except BaseException:
                    registry.close_all()
                    system_engine.dispose()
                    raise
                request.app.state.system_engine = system_engine
                request.app.state.engine_registry = registry
                request.app.state.default_context = context
                request.app.state.engine = context.engine
            else:
                engine = make_engine(request.app.state.db_url)
                init_db(engine)
                request.app.state.engine = engine
            runtime_disposed = False

        try:
            import_data_root(
                archive,
                request.app.state.data_dir,
                before_swap=dispose_all,
                after_swap=rebuild_runtime,
            )
        except UnsafeArchiveError as exc:
            raise ApiException(400, "UNSAFE_ARCHIVE", str(exc)) from exc
        except InvalidArchiveError as exc:
            raise ApiException(400, "INVALID_ARCHIVE", str(exc)) from exc
        except BaseException:
            if runtime_disposed:
                rebuild_runtime()
            raise
        env_settings.cache_clear()
    refresh_app_settings(
        request.app,
        Settings(_env_file=request.app.state.env_path),  # type: ignore[call-arg]
    )
    return {"status": "imported"}
