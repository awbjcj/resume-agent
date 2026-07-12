from typing import Literal

from pydantic import Field, field_validator

from resume_agent.api.schemas.base import CamelModel


class LoginRequest(CamelModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.strip().casefold()


class RegisterRequest(CamelModel):
    username: str = Field(pattern=r"^[a-z][a-z0-9._-]{2,31}$")
    password: str = Field(min_length=12, max_length=1024)
    invite_code: str = Field(min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        return value.strip().casefold()


class MeResponse(CamelModel):
    username: str | None = None
    role: Literal["admin", "user"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    auth_required: bool = False


class LinkTokenRequest(CamelModel):
    purpose: Literal["sse", "download"]


class LinkTokenResponse(CamelModel):
    token: str
    expires_in_seconds: int
