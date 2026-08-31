from pydantic import Field

from resume_tailor_harness.api.schemas.base import CamelModel


class SystemDefaults(CamelModel):
    weekly_token_budget: int = Field(ge=0)
    max_active_jobs: int = Field(ge=0)
    max_concurrent_runs: int = Field(ge=0)


class SystemDefaultsUpdate(CamelModel):
    weekly_token_budget: int | None = Field(default=None, ge=0)
    max_active_jobs: int = Field(ge=0)
    max_concurrent_runs: int = Field(ge=0)


class UserUsage(CamelModel):
    user_id: str
    username: str
    weighted_total: float
    own_key_weighted_total: float
    calls: int


class UsageReport(CamelModel):
    users: list[UserUsage]
