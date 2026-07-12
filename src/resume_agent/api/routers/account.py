from __future__ import annotations

import shutil
import tempfile
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from resume_agent.api import auth
from resume_agent.api.deps import get_settings_dep
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.account import (
    AccountUsage,
    PasswordChangeRequest,
    TokenCreated,
    TokenCreateRequest,
    TokenInfo,
    TokenList,
)
from resume_agent.config import Settings
from resume_agent.services.backup import export_data_root
from resume_agent.tenancy.context import require_context
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
    budget = resolve_limit(
        user.weekly_token_budget if user is not None else None,
        system_default(engine, "weekly_token_budget", DEFAULT_WEEKLY_TOKEN_BUDGET),
    )
    return AccountUsage(
        weighted_total=weekly_usage(engine, context.user_id),
        own_key_weighted_total=float(own_key),
        budget=budget,
    )
