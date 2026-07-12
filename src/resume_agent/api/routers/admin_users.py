from __future__ import annotations

import shutil
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from sqlmodel import col

from resume_agent.api import auth
from resume_agent.api.deps import require_admin
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.admin_users import (
    AdminUser,
    AdminUserList,
    AdminUserPatch,
    ResetPasswordRequest,
)
from resume_agent.tenancy.context import UserContext
from resume_agent.tenancy.limits import weekly_usage
from resume_agent.tenancy.system_db import ApiToken, User
from resume_agent.tenancy.workspace import workspace_paths
from resume_agent.tracking.tables import Job

router = APIRouter(prefix="/admin/users", tags=["admin"])


def _last_admin(session: Session) -> bool:
    count = session.execute(
        select(func.count())
        .select_from(User)
        .where(User.role == "admin", col(User.disabled_at).is_(None))
    ).scalar_one()
    return int(count) <= 1


def _active_jobs(request: Request, user_id: str) -> int:
    paths = workspace_paths(request.app.state.data_dir, user_id)
    if not paths.db_file.is_file():
        return 0
    engine = request.app.state.engine_registry.get(user_id, paths.db_url)
    with Session(engine) as session:
        return int(
            session.execute(
                select(func.count())
                .select_from(Job)
                .where(col(Job.archived_at).is_(None))
            ).scalar_one()
        )


@router.get("")
def list_users(
    request: Request, _context: UserContext = Depends(require_admin)
) -> AdminUserList:
    engine = request.app.state.system_engine
    with Session(engine) as session:
        rows = session.execute(select(User).order_by(User.created_at)).scalars().all()
        return AdminUserList(
            users=[
                AdminUser(
                    id=row.id,
                    username=row.username,
                    role=row.role,
                    created_at=row.created_at,
                    disabled_at=row.disabled_at,
                    weekly_token_budget=row.weekly_token_budget,
                    max_active_jobs=row.max_active_jobs,
                    max_concurrent_runs=row.max_concurrent_runs,
                    weekly_usage=weekly_usage(engine, row.id),
                    active_jobs=_active_jobs(request, row.id),
                )
                for row in rows
            ]
        )


@router.patch("/{user_id}")
def patch_user(
    user_id: str,
    body: AdminUserPatch,
    request: Request,
    context: UserContext = Depends(require_admin),
) -> dict[str, str]:
    with Session(request.app.state.system_engine) as session:
        user = session.get(User, user_id)
        if user is None:
            raise ApiException(404, "NOT_FOUND", "No such user")
        if body.role is not None and body.role != user.role:
            if user.role == "admin" and _last_admin(session):
                raise ApiException(409, "LAST_ADMIN", "Cannot demote the last admin")
            user.role = body.role
        if body.disabled is not None:
            if body.disabled and user.id == context.user_id:
                raise ApiException(409, "SELF_DISABLE", "Cannot disable yourself")
            user.disabled_at = datetime.now(timezone.utc) if body.disabled else None
        for field in ("weekly_token_budget", "max_active_jobs", "max_concurrent_runs"):
            if field in body.model_fields_set:
                setattr(user, field, getattr(body, field))
        session.commit()
    return {"status": "updated"}


@router.post("/{user_id}/reset-password")
def reset_password(
    user_id: str,
    body: ResetPasswordRequest,
    request: Request,
    _context: UserContext = Depends(require_admin),
) -> dict[str, str]:
    with Session(request.app.state.system_engine) as session:
        user = session.get(User, user_id)
        if user is None:
            raise ApiException(404, "NOT_FOUND", "No such user")
        user.password_hash = auth.hash_password(body.password)
        session.commit()
    return {"status": "reset"}


@router.delete("/{user_id}")
def delete_user(
    user_id: str,
    request: Request,
    confirm: str = "",
    context: UserContext = Depends(require_admin),
) -> dict[str, str]:
    if confirm != "DELETE":
        raise ApiException(400, "CONFIRM_REQUIRED", "Pass ?confirm=DELETE")
    if user_id == context.user_id:
        raise ApiException(409, "SELF_DELETE", "Cannot delete yourself")
    if request.app.state.run_manager.list_active(user_id=user_id):
        raise ApiException(409, "RUNS_ACTIVE", "The user has active runs")
    paths = workspace_paths(request.app.state.data_dir, user_id)
    tombstone = paths.root.with_name(f".{user_id}.deleting-{uuid.uuid4().hex}")
    with Session(request.app.state.system_engine) as session:
        user = session.get(User, user_id)
        if user is None:
            raise ApiException(404, "NOT_FOUND", "No such user")
        if user.role == "admin" and _last_admin(session):
            raise ApiException(409, "LAST_ADMIN", "Cannot delete the last admin")
        request.app.state.engine_registry.evict(user_id)
        if paths.root.exists():
            paths.root.rename(tombstone)
        try:
            session.execute(delete(ApiToken).where(ApiToken.user_id == user_id))
            session.delete(user)
            session.commit()
        except BaseException:
            session.rollback()
            if tombstone.exists() and not paths.root.exists():
                tombstone.rename(paths.root)
            raise
    shutil.rmtree(tombstone, ignore_errors=True)
    return {"status": "deleted"}
