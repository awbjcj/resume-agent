from datetime import datetime

from pydantic import Field

from resume_tailor_harness.api.schemas.base import CamelModel


class InviteMintRequest(CamelModel):
    expires_in_days: int = Field(default=14, ge=1, le=365)


class InviteMinted(CamelModel):
    id: str
    code: str
    expires_at: datetime


class InviteInfo(CamelModel):
    id: str
    created_by: str
    created_at: datetime
    expires_at: datetime
    used_by: str | None = None
    used_at: datetime | None = None
    revoked_at: datetime | None = None


class InviteList(CamelModel):
    invites: list[InviteInfo]
