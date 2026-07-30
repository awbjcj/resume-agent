from datetime import datetime

from pydantic import Field, field_validator

from resume_agent.api.schemas.base import CamelModel


class AdminUser(CamelModel):
    id: str
    username: str
    role: str
    created_at: datetime
    disabled_at: datetime | None = None
    weekly_token_budget: int | None = None
    max_active_jobs: int | None = None
    max_concurrent_runs: int | None = None
    shared_key_access: bool = True
    weekly_usage: float = 0
    active_jobs: int = 0


class AdminUserList(CamelModel):
    users: list[AdminUser]


class AdminUserPatch(CamelModel):
    role: str | None = None
    disabled: bool | None = None
    weekly_token_budget: int | None = Field(default=None, ge=0)
    max_active_jobs: int | None = Field(default=None, ge=0)
    max_concurrent_runs: int | None = Field(default=None, ge=0)
    shared_key_access: bool | None = None

    @field_validator("role")
    @classmethod
    def valid_role(cls, value: str | None) -> str | None:
        if value is not None and value not in {"admin", "user"}:
            raise ValueError("role must be admin or user")
        return value


class ResetPasswordRequest(CamelModel):
    password: str = Field(min_length=12, max_length=1024)
