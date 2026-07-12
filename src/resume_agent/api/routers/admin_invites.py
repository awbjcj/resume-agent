from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from resume_agent.api.deps import require_admin
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.admin_invites import (
    InviteInfo,
    InviteList,
    InviteMinted,
    InviteMintRequest,
)
from resume_agent.tenancy.context import UserContext
from resume_agent.tenancy.secrets import hash_secret, mint_secret
from resume_agent.tenancy.system_db import InviteCode

router = APIRouter(prefix="/admin/invites", tags=["admin"])


@router.post("", status_code=201)
def mint_invite(
    body: InviteMintRequest,
    request: Request,
    context: UserContext = Depends(require_admin),
) -> InviteMinted:
    raw = mint_secret("inv_")
    row = InviteCode(
        id=uuid.uuid4().hex[:12],
        code_hash=hash_secret(raw),
        created_by=context.user_id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=body.expires_in_days),
    )
    with Session(request.app.state.system_engine, expire_on_commit=False) as session:
        session.add(row)
        session.commit()
    return InviteMinted(id=row.id, code=raw, expires_at=row.expires_at)


@router.get("")
def list_invites(
    request: Request, _context: UserContext = Depends(require_admin)
) -> InviteList:
    with Session(request.app.state.system_engine) as session:
        rows = (
            session.execute(select(InviteCode).order_by(InviteCode.created_at.desc()))
            .scalars()
            .all()
        )
        return InviteList(invites=[InviteInfo.model_validate(row) for row in rows])


@router.delete("/{invite_id}")
def revoke_invite(
    invite_id: str,
    request: Request,
    _context: UserContext = Depends(require_admin),
) -> dict[str, str]:
    with Session(request.app.state.system_engine) as session:
        row = session.get(InviteCode, invite_id)
        if row is None:
            raise ApiException(404, "NOT_FOUND", "No such invite")
        if row.used_at is not None:
            raise ApiException(409, "INVITE_USED", "Invite already used")
        row.revoked_at = datetime.now(timezone.utc)
        session.commit()
    return {"status": "revoked"}
