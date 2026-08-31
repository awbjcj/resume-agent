"""Application timeline event request and response contracts."""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import Field, computed_field, field_validator, model_validator

from resume_tailor_harness.api.schemas.base import CamelModel


class ApplicationEventOut(CamelModel):
    id: int
    application_id: int
    kind: str
    custom_label: str | None = None
    sequence: int
    sequence_override: int | None = None
    occurred_at: datetime | None = None
    all_day: bool
    timezone: str | None = None
    duration_minutes: int | None = None
    modality: str | None = None
    platform: str | None = None
    platform_other: str | None = None
    location_or_link: str | None = None
    interviewers: str | None = None
    result: str
    notes: str | None = None
    reflection: str | None = None
    comp_base: int | None = None
    comp_bonus: int | None = None
    comp_equity_annual: int | None = None
    comp_signing: int | None = None
    comp_currency: str | None = None
    source: str
    created_at: datetime
    updated_at: datetime

    @field_validator("occurred_at", "created_at", "updated_at", mode="before")
    @classmethod
    def mark_persisted_utc(cls, value: datetime | None) -> datetime | None:
        if value is None or value.tzinfo is not None:
            return value
        return value.replace(tzinfo=timezone.utc)

    @computed_field
    @property
    def total_comp(self) -> int | None:
        parts = (
            self.comp_base,
            self.comp_bonus,
            self.comp_equity_annual,
            self.comp_signing,
        )
        return (
            sum(value for value in parts if value is not None)
            if any(value is not None for value in parts)
            else None
        )


class ApplicationEventCreate(CamelModel):
    kind: str
    custom_label: str | None = None
    sequence: int | None = Field(default=None, ge=1)
    occurred_at: datetime | None = None
    all_day: bool = False
    timezone: str | None = None
    duration_minutes: int | None = None
    modality: str | None = None
    platform: str | None = None
    platform_other: str | None = None
    location_or_link: str | None = None
    interviewers: str | None = None
    result: str = "pending"
    notes: str | None = None
    reflection: str | None = None
    comp_base: int | None = None
    comp_bonus: int | None = None
    comp_equity_annual: int | None = None
    comp_signing: int | None = None
    comp_currency: str | None = None

    @field_validator("occurred_at")
    @classmethod
    def require_aware_datetime(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("occurred_at must include a UTC offset")
        return value


class ApplicationEventUpdate(CamelModel):
    kind: str | None = None
    custom_label: str | None = None
    sequence: int | None = Field(default=None, ge=1)
    occurred_at: datetime | None = None
    all_day: bool | None = None
    timezone: str | None = None
    duration_minutes: int | None = None
    modality: str | None = None
    platform: str | None = None
    platform_other: str | None = None
    location_or_link: str | None = None
    interviewers: str | None = None
    result: str | None = None
    notes: str | None = None
    reflection: str | None = None
    comp_base: int | None = None
    comp_bonus: int | None = None
    comp_equity_annual: int | None = None
    comp_signing: int | None = None
    comp_currency: str | None = None

    @field_validator("occurred_at")
    @classmethod
    def require_aware_datetime(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("occurred_at must include a UTC offset")
        return value

    @model_validator(mode="before")
    @classmethod
    def reject_null_required_fields(cls, value: object) -> object:
        if isinstance(value, dict):
            for field in ("kind", "all_day", "allDay", "result"):
                if field in value and value[field] is None:
                    raise ValueError(f"{field} cannot be null")
        return value
