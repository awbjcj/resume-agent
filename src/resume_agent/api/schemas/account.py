from datetime import datetime
from typing import Literal

from pydantic import EmailStr, Field, field_validator

from resume_agent.api.schemas.base import CamelModel


class TokenCreateRequest(CamelModel):
    name: str = Field(min_length=1, max_length=80)


class TokenCreated(CamelModel):
    id: str
    name: str
    token: str


class TokenInfo(CamelModel):
    id: str
    name: str
    created_at: datetime
    last_used_at: datetime | None = None


class TokenList(CamelModel):
    tokens: list[TokenInfo]


class PasswordChangeRequest(CamelModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)


class SetEmailRequest(CamelModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().casefold()


class VerifyAccountEmailRequest(SetEmailRequest):
    code: str = Field(pattern=r"^\d{6}$")


class AccountUsage(CamelModel):
    weighted_total: float
    own_key_weighted_total: float
    budget: int


class ResetRequest(CamelModel):
    scope: Literal["jobs", "profile", "all"]


class ResetReportOut(CamelModel):
    scope: Literal["jobs", "profile", "all"]
    rows_deleted: dict[str, int]
    areas_cleared: list[str]
    failures: dict[str, str]
