from __future__ import annotations

import shutil
import sqlite3
import tempfile
import uuid
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal, cast

from fastapi import APIRouter, Depends, Request, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlmodel import Session as WorkspaceSession
from starlette.background import BackgroundTask

from resume_agent.api import auth, auth_codes
from resume_agent.api.deps import get_session, get_settings_dep
from resume_agent.api.errors import ApiException
from resume_agent.api.password_policy import validate_password
from resume_agent.api.routers.auth_register import rate_event
from resume_agent.api.runs.manager import RunResetConflict
from resume_agent.api.uploads import UploadTooLargeError, copy_upload
from resume_agent.api.schemas.account import (
    AccountUsage,
    PasswordChangeRequest,
    ResetReportOut,
    ResetRequest,
    SetEmailRequest,
    TokenCreated,
    TokenCreateRequest,
    TokenInfo,
    TokenList,
    VerifyAccountEmailRequest,
)
from resume_agent.api.schemas.auth import MeResponse
from resume_agent.api.schemas.auth_email import CodeSentResponse
from resume_agent.config import Settings
from resume_agent.mail import messages
from resume_agent.mail.mailer import MailDeliveryError
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
from resume_agent.tenancy.system_db import (
    ApiToken,
    PasswordResetCode,
    UsageEvent,
    User,
    has_password,
)
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
        validate_password(
            body.new_password,
            email=user.email or "",
            display_name=user.username,
            checker=request.app.state.breach_checker,
        )
        user.password_hash = auth.hash_password(body.new_password)
        user.session_epoch += 1
        session.commit()
        password_hash, epoch, email = (
            user.password_hash,
            user.session_epoch,
            user.email,
        )
    token = auth.issue_user_session(
        settings,
        user_id=context.user_id,
        password_hash=password_hash,
        epoch=epoch,
    )
    auth.set_session_cookie(request, response, token)
    if email:
        message = messages.password_changed(settings.app_base_url)
        request.app.state.mailer.notify(
            to=email, subject=message.subject, body=message.body
        )
    return {"status": "changed"}


@router.post("/email", status_code=202)
def set_email(
    body: SetEmailRequest,
    request: Request,
    settings: Settings = Depends(get_settings_dep),
) -> CodeSentResponse:
    context = require_context()
    rate_event(request, body.email)
    code = auth_codes.generate_code()
    row_id = uuid.uuid4().hex[:12]
    with Session(request.app.state.system_engine) as session:
        owner = session.execute(
            select(User.id).where(User.email == body.email)
        ).scalar()
        if owner is not None and owner != context.user_id:
            raise ApiException(409, "EMAIL_TAKEN", "That email is already in use")
        session.execute(
            delete(PasswordResetCode).where(
                PasswordResetCode.user_id == context.user_id,
                PasswordResetCode.pending_email.is_not(None),
            )
        )
        session.add(
            PasswordResetCode(
                id=row_id,
                user_id=context.user_id,
                code_hash=auth_codes.hash_code(code, settings),
                expires_at=auth_codes.expires_at(),
                pending_email=body.email,
            )
        )
        session.commit()
    message = messages.verification_code(code)
    try:
        request.app.state.mailer.send(
            to=body.email, subject=message.subject, body=message.body
        )
    except MailDeliveryError as exc:
        with Session(request.app.state.system_engine) as session:
            session.execute(
                delete(PasswordResetCode).where(
                    PasswordResetCode.id == row_id,
                )
            )
            session.commit()
        raise ApiException(503, "MAIL_UNAVAILABLE", "Unable to send email") from exc
    return CodeSentResponse()


@router.post("/email/verify")
def verify_account_email(
    body: VerifyAccountEmailRequest,
    request: Request,
    settings: Settings = Depends(get_settings_dep),
) -> MeResponse:
    context = require_context()
    rate_event(request, body.email)
    now = datetime.now(timezone.utc)
    with Session(request.app.state.system_engine) as session:
        row = (
            session.execute(
                select(PasswordResetCode).where(
                    PasswordResetCode.user_id == context.user_id,
                    PasswordResetCode.pending_email == body.email,
                    PasswordResetCode.consumed_at.is_(None),
                )
            )
            .scalars()
            .first()
        )
        if row is None:
            raise ApiException(400, "CODE_INVALID", "Invalid verification code")
        verdict = auth_codes.check_code(
            cast(auth_codes.CodeRow, row), body.code, settings, now=now
        )
        if verdict is not auth_codes.CodeVerdict.OK:
            session.commit()
            raise ApiException(
                400, f"CODE_{verdict.value.upper()}", "Invalid verification code"
            )
        user = session.get(User, context.user_id)
        if user is None:
            raise ApiException(404, "NOT_FOUND", "Account not found")
        owner = session.execute(
            select(User.id).where(User.email == body.email)
        ).scalar()
        if owner is not None and owner != user.id:
            raise ApiException(409, "EMAIL_TAKEN", "That email is already in use")
        user.email = body.email
        user.email_verified_at = now
        row.consumed_at = now
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise ApiException(
                409, "EMAIL_TAKEN", "That email is already in use"
            ) from exc
        return MeResponse(
            username=user.username,
            email=user.email,
            email_verified=True,
            needs_email=False,
            google_linked=user.google_sub is not None,
            role=cast(Literal["admin", "user"], user.role),
            auth_required=True,
        )


@router.post("/sessions/revoke-all")
def revoke_all_sessions(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings_dep),
) -> dict[str, str]:
    context = require_context()
    with Session(request.app.state.system_engine) as session:
        user = session.get(User, context.user_id)
        if user is None:
            raise ApiException(404, "NOT_FOUND", "Account not found")
        user.session_epoch += 1
        session.commit()
        token = auth.issue_user_session(
            settings,
            user_id=user.id,
            password_hash=user.password_hash,
            epoch=user.session_epoch,
        )
    auth.set_session_cookie(request, response, token)
    return {"status": "revoked"}


@router.delete("/google")
def unlink_google(request: Request) -> MeResponse:
    context = require_context()
    settings = request.app.state.settings
    with Session(request.app.state.system_engine) as session:
        user = session.get(User, context.user_id)
        if user is None:
            raise ApiException(404, "NOT_FOUND", "Account not found")
        if not has_password(user):
            raise ApiException(
                409, "PASSWORD_REQUIRED", "Set a password before unlinking Google"
            )
        user.google_sub = None
        session.commit()
        email, username, role, verified = (
            user.email,
            user.username,
            user.role,
            user.email_verified_at is not None,
        )
    if email:
        message = messages.google_unlinked(settings.app_base_url)
        request.app.state.mailer.notify(
            to=email, subject=message.subject, body=message.body
        )
    return MeResponse(
        username=username,
        email=email,
        email_verified=verified,
        needs_email=email is None,
        google_linked=False,
        role=cast(Literal["admin", "user"], role),
        auth_required=True,
    )


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
    paths = (
        ResetPaths.from_workspace(context.paths)
        if context is not None
        else ResetPaths.legacy(
            data_dir=request.app.state.data_dir,
            output_dir=Path("output"),
            runs_dir=request.app.state.run_manager.root,
        )
    )
    # The reset barrier makes the active-runs check and the truncate atomic: no
    # run can be submitted for this owner between the two.
    try:
        with request.app.state.run_manager.reset_guard(user_id):
            report = reset_workspace(session, paths, ResetScope(body.scope))
    except RunResetConflict as exc:
        raise ApiException(
            409, "RUNS_ACTIVE", "Refusing while your runs are active"
        ) from exc
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
