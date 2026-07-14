from __future__ import annotations

import shutil
import sqlite3
import tempfile
import uuid
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Request, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlmodel import Session as WorkspaceSession
from starlette.background import BackgroundTask

from resume_agent.api import auth
from resume_agent.api.deps import get_session, get_settings_dep
from resume_agent.api.errors import ApiException
from resume_agent.api.uploads import UploadTooLargeError, copy_upload
from resume_agent.api.schemas.account import (
    AccountUsage,
    PasswordChangeRequest,
    ResetReportOut,
    ResetRequest,
    TokenCreated,
    TokenCreateRequest,
    TokenInfo,
    TokenList,
)
from resume_agent.config import Settings
from resume_agent.services.backup import (
    InvalidArchiveError,
    UnsafeArchiveError,
    export_data_root,
    import_data_root,
)
from resume_agent.services.reset import ResetPaths, ResetScope, reset_workspace
from resume_agent.tenancy.context import current_context, require_context
from resume_agent.tenancy.limits import (
    DEFAULT_WEEKLY_TOKEN_BUDGET,
    resolve_limit,
    system_default,
    weekly_usage,
)
from resume_agent.tenancy.secrets import hash_secret, mint_secret
from resume_agent.tenancy.system_db import ApiToken, UsageEvent, User
from resume_agent.tenancy.workspace import workspace_paths

router = APIRouter(prefix="/account", tags=["account"])
link_router = APIRouter(prefix="/account", tags=["account"])


def _validate_workspace_stage(stage: Path) -> None:
    database = stage / "resume_agent.db"
    if not database.is_file():
        raise InvalidArchiveError("workspace archive is missing resume_agent.db")
    try:
        with closing(
            sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
        ) as connection:
            if connection.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise InvalidArchiveError("workspace database failed integrity check")
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
    except sqlite3.Error as exc:
        raise InvalidArchiveError("workspace database is not valid SQLite") from exc
    if "jobs" not in tables:
        raise InvalidArchiveError("workspace database is missing the jobs table")


@router.post("/tokens", status_code=201)
def mint_token(body: TokenCreateRequest, request: Request) -> TokenCreated:
    context = require_context()
    raw = mint_secret("rat_")
    token = ApiToken(
        id=uuid.uuid4().hex[:12],
        user_id=context.user_id,
        name=body.name.strip(),
        token_hash=hash_secret(raw),
    )
    with Session(request.app.state.system_engine) as session:
        session.add(token)
        session.commit()
        session.refresh(token)
        return TokenCreated(id=token.id, name=token.name, token=raw)


@router.get("/tokens")
def list_tokens(request: Request) -> TokenList:
    context = require_context()
    with Session(request.app.state.system_engine) as session:
        tokens = (
            session.execute(
                select(ApiToken)
                .where(
                    ApiToken.user_id == context.user_id, ApiToken.revoked_at.is_(None)
                )
                .order_by(ApiToken.created_at)
            )
            .scalars()
            .all()
        )
        return TokenList(tokens=[TokenInfo.model_validate(token) for token in tokens])


@router.delete("/tokens/{token_id}", status_code=204)
def revoke_token(token_id: str, request: Request) -> Response:
    context = require_context()
    with Session(request.app.state.system_engine) as session:
        token = session.get(ApiToken, token_id)
        if token is None or token.user_id != context.user_id:
            raise ApiException(404, "NOT_FOUND", "No such token")
        token.revoked_at = datetime.now(timezone.utc)
        session.commit()
    return Response(status_code=204)


@router.post("/password")
def change_password(
    body: PasswordChangeRequest,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, str]:
    context = require_context()
    with Session(request.app.state.system_engine, expire_on_commit=False) as session:
        user = session.get(User, context.user_id)
        if user is None or not auth.verify_password(
            body.current_password, user.password_hash
        ):
            raise ApiException(401, "UNAUTHORIZED", "Current password is incorrect")
        user.password_hash = auth.hash_password(body.new_password)
        session.commit()
        password_hash = user.password_hash
    token = auth.issue_user_session(
        settings, user_id=context.user_id, password_hash=password_hash
    )
    response.set_cookie(
        auth.SESSION_COOKIE,
        token,
        max_age=auth.SESSION_LIFETIME_SECONDS,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/",
    )
    return {"status": "changed"}


@router.post("/reset")
def reset_data(
    body: ResetRequest,
    request: Request,
    confirm: str = "",
    session: WorkspaceSession = Depends(get_session),
) -> ResetReportOut:
    if confirm != "RESET":
        raise ApiException(
            400,
            "CONFIRM_REQUIRED",
            "Reset destroys data; pass ?confirm=RESET",
        )
    context = current_context()
    user_id = context.user_id if context is not None else None
    if request.app.state.run_manager.list_active(user_id=user_id):
        raise ApiException(409, "RUNS_ACTIVE", "Refusing while your runs are active")
    paths = (
        ResetPaths.from_workspace(context.paths)
        if context is not None
        else ResetPaths.legacy(
            data_dir=request.app.state.data_dir,
            output_dir=Path("output"),
            runs_dir=request.app.state.run_manager.root,
        )
    )
    report = reset_workspace(session, paths, ResetScope(body.scope))
    return ResetReportOut(
        scope=report.scope.value,
        rows_deleted=report.rows_deleted,
        areas_cleared=report.areas_cleared,
        failures=report.failures,
    )


@link_router.get("/export")
def export_workspace(request: Request) -> FileResponse:
    context = require_context()
    if request.app.state.run_manager.list_active(user_id=context.user_id):
        raise ApiException(409, "RUNS_ACTIVE", "Refusing while your runs are active")
    paths = workspace_paths(request.app.state.data_dir, context.user_id)
    temporary = Path(tempfile.mkdtemp(prefix="ra-workspace-export-"))
    try:
        archive = export_data_root(paths.root, paths.db_url, temporary)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return FileResponse(
        archive,
        media_type="application/gzip",
        filename=f"workspace-{context.username}-{date.today().isoformat()}.tar.gz",
        background=BackgroundTask(shutil.rmtree, temporary, ignore_errors=True),
    )


@router.post("/import")
def import_workspace(
    request: Request,
    file: UploadFile,
    confirm: str = "",
) -> dict[str, str]:
    if confirm != "REPLACE":
        raise ApiException(
            400,
            "CONFIRM_REQUIRED",
            "Import replaces your workspace; pass ?confirm=REPLACE",
        )
    context = require_context()
    if request.app.state.run_manager.list_active(user_id=context.user_id):
        raise ApiException(409, "RUNS_ACTIVE", "Refusing while your runs are active")
    registry = request.app.state.engine_registry
    if registry is None:
        raise ApiException(
            400, "NO_WORKSPACE", "Workspace import requires multi-user mode"
        )
    paths = workspace_paths(request.app.state.data_dir, context.user_id)

    with tempfile.TemporaryDirectory(prefix="ra-workspace-import-") as temporary:
        archive = Path(temporary) / "import.tar.gz"
        try:
            copy_upload(file, archive, max_bytes=256 * 1024 * 1024)
            import_data_root(
                archive,
                paths.root,
                validate_staged=_validate_workspace_stage,
                before_swap=lambda: registry.evict(context.user_id),
                after_swap=lambda: registry.get(context.user_id, paths.db_url),
            )
        except UploadTooLargeError as exc:
            raise ApiException(413, "UPLOAD_TOO_LARGE", str(exc)) from exc
        except UnsafeArchiveError as exc:
            raise ApiException(400, "UNSAFE_ARCHIVE", str(exc)) from exc
        except InvalidArchiveError as exc:
            raise ApiException(400, "INVALID_ARCHIVE", str(exc)) from exc
        except BaseException:
            # The staged swap has restored the old workspace. Rebind it so the
            # next request never inherits a disposed engine.
            registry.evict(context.user_id)
            registry.get(context.user_id, paths.db_url)
            raise
    return {"status": "imported"}


@router.get("/usage")
def account_usage(request: Request) -> AccountUsage:
    context = require_context()
    engine = request.app.state.system_engine
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    with Session(engine) as session:
        user = session.get(User, context.user_id)
        own_key = session.execute(
            select(func.coalesce(func.sum(UsageEvent.weighted_total), 0.0)).where(
                UsageEvent.user_id == context.user_id,
                UsageEvent.own_key.is_(True),
                UsageEvent.ts >= cutoff,
            )
        ).scalar_one()
    budget = (
        0
        if context.is_admin
        else resolve_limit(
            user.weekly_token_budget if user is not None else None,
            system_default(engine, "weekly_token_budget", DEFAULT_WEEKLY_TOKEN_BUDGET),
        )
    )
    return AccountUsage(
        weighted_total=weekly_usage(engine, context.user_id),
        own_key_weighted_total=float(own_key),
        budget=budget,
    )
