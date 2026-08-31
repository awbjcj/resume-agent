from datetime import datetime, timezone
from typing import Literal

from pydantic import Field, field_serializer, field_validator, model_validator

from resume_tailor_harness.api.schemas.base import CamelModel, Page

CycleUnit = Literal["WEEK", "MONTH"]
QuotaStatus = Literal["ACTIVE", "EXHAUSTED", "OVERAGE", "UNLIMITED"]
RatePeriod = Literal["peak", "off_peak"]


class UtcCamelModel(CamelModel):
    @field_serializer("*", when_used="json", check_fields=False)
    def serialize_utc(self, value):
        if not isinstance(value, datetime):
            return value
        aware = (
            value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        )
        return aware.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class QuotaTierOut(UtcCamelModel):
    id: str
    name: str
    cycle_unit: CycleUnit
    cycle_count: int
    allowance_micros: int | None
    is_default: bool
    archived_at: datetime | None
    member_count: int = 0
    spend_micros: int = 0


class QuotaPlatformSummary(UtcCamelModel):
    monthly_spend_micros: int
    monthly_cap_micros: int
    remaining_micros: int
    unpriced_call_count: int
    next_reset_at: datetime


class QuotaTierPage(Page[QuotaTierOut]):
    pass


class QuotaTierCreate(CamelModel):
    id: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,31}$")
    name: str = Field(min_length=1, max_length=80)
    cycle_unit: CycleUnit
    cycle_count: int = Field(ge=1, le=52)
    allowance_micros: int | None = Field(default=None, ge=0)
    reason: str = Field(min_length=1, max_length=500)


class QuotaTierPatch(CamelModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    cycle_unit: CycleUnit | None = None
    cycle_count: int | None = Field(default=None, ge=1, le=52)
    allowance_micros: int | None = Field(default=None, ge=0)
    archived: bool | None = None
    reason: str = Field(min_length=1, max_length=500)


class QuotaAccountOut(UtcCamelModel):
    user_id: str
    username: str
    disabled: bool
    tier_id: str
    allowance_micros: int | None
    override_micros: int | None
    spent_micros: int
    recurring_remaining_micros: int | None
    credit_balance_micros: int
    remaining_micros: int | None
    overage_micros: int
    period_start: datetime
    period_end: datetime
    status: QuotaStatus
    shared_cost_micros: int
    byok_cost_micros: int
    total_tokens: int


class QuotaAccountPage(Page[QuotaAccountOut]):
    pass


class QuotaLedgerEntryOut(UtcCamelModel):
    id: int
    kind: str
    amount_micros: int
    recurring_micros: int
    credit_micros: int
    overage_micros: int
    actor_user_id: str | None
    reason: str | None
    created_at: datetime


class QuotaLedgerPage(Page[QuotaLedgerEntryOut]):
    pass


class QuotaAccountPatch(CamelModel):
    tier_id: str | None = None
    allowance_override_micros: int | None = Field(default=None, ge=0)
    reason: str = Field(min_length=1, max_length=500)


class QuotaOperationPreviewCreate(CamelModel):
    target_type: Literal["USER", "TIER", "ALL_MEMBERS"]
    target_value: str | None = None
    action_type: Literal["RESET_CURRENT_PERIOD", "GRANT_CREDIT", "DEBIT_CREDIT"]
    amount_micros: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def normalize_target(self) -> "QuotaOperationPreviewCreate":
        """Make a preview target explicit before it reaches quota business logic."""
        if self.target_type == "ALL_MEMBERS":
            # A stale value from a client-side scope switch must never be
            # recorded as though it narrowed an all-member operation.
            self.target_value = None
            return self

        target = (self.target_value or "").strip()
        if not target:
            label = "member" if self.target_type == "USER" else "tier"
            raise ValueError(f"a {label} target is required")
        self.target_value = target
        return self


class QuotaOperationPreviewOut(UtcCamelModel):
    id: str
    target_type: str
    target_value: str | None
    action_type: str
    amount_micros: int | None
    affected_count: int
    total_effect_micros: int
    expires_at: datetime


class QuotaOperationCommit(CamelModel):
    preview_id: str
    reason: str = Field(min_length=1, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=64)


class QuotaOperationOut(UtcCamelModel):
    id: str
    action_type: str
    target_type: str
    target_value: str | None
    amount_micros: int | None
    reason: str
    affected_count: int
    actor_user_id: str
    created_at: datetime


class QuotaOperationPage(Page[QuotaOperationOut]):
    pass


class LlmRateOut(UtcCamelModel):
    id: str
    provider: str
    model: str
    context_min_tokens: int
    context_max_tokens: int | None
    input_micros_per_million: int
    cache_read_micros_per_million: int | None
    cache_write_micros_per_million: int | None
    output_micros_per_million: int
    tool_micros_per_unit: int | None
    rate_period: RatePeriod | None
    effective_from: datetime
    effective_to: datetime | None
    source_url: str


class LlmRatePage(Page[LlmRateOut]):
    pass


class LlmRateCreate(CamelModel):
    provider: str = Field(min_length=1, max_length=32)
    model: str = Field(min_length=1, max_length=160)
    context_min_tokens: int = Field(default=0, ge=0)
    context_max_tokens: int | None = Field(default=None, ge=0)
    input_micros_per_million: int = Field(ge=0)
    cache_read_micros_per_million: int | None = Field(default=None, ge=0)
    cache_write_micros_per_million: int | None = Field(default=None, ge=0)
    output_micros_per_million: int = Field(ge=0)
    tool_micros_per_unit: int | None = Field(default=None, ge=0)
    rate_period: RatePeriod | None = None
    effective_from: datetime
    effective_to: datetime | None = None
    source_url: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=500)

    @field_validator("effective_from", "effective_to")
    @classmethod
    def require_utc_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("effective timestamps must include a UTC offset")
        return value.astimezone(timezone.utc)
