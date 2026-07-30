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
    quota: "QuotaSnapshotOut | None" = None
    costs: "CostTotals" = Field(default_factory=lambda: CostTotals())
    shared_tokens: "TokenTotals" = Field(default_factory=lambda: TokenTotals())
    byok_tokens: "TokenTotals" = Field(default_factory=lambda: TokenTotals())
    all_tokens: "TokenTotals" = Field(default_factory=lambda: TokenTotals())


class TokenTotals(CamelModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    audio_tokens: int = 0
    total_tokens: int = 0


class CostTotals(CamelModel):
    shared_quota_cost_micros: int = 0
    byok_estimated_cost_micros: int = 0
    tool_cost_micros: int = 0
    unpriced_call_count: int = 0


class QuotaSnapshotOut(CamelModel):
    tier_id: str
    tier_name: str
    period_start: datetime
    period_end: datetime
    recurring_allowance_micros: int | None
    allowance_override_micros: int | None
    spend_micros: int
    credit_balance_micros: int
    remaining_micros: int | None
    overage_micros: int
    next_reset_at: datetime
    enforcement_status: str


class ResetRequest(CamelModel):
    scope: Literal["jobs", "profile", "all"]


class ResetReportOut(CamelModel):
    scope: Literal["jobs", "profile", "all"]
    rows_deleted: dict[str, int]
    areas_cleared: list[str]
    failures: dict[str, str]
