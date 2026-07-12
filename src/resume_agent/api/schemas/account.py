from datetime import datetime

from pydantic import Field

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


class AccountUsage(CamelModel):
    weighted_total: float
    own_key_weighted_total: float
    budget: int
