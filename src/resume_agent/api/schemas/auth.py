from typing import Literal

from pydantic import Field, field_validator

from resume_agent.api.schemas.base import CamelModel


class LoginRequest(CamelModel):
    identifier: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("identifier")
    @classmethod
    def normalize_identifier(cls, value: str) -> str:
        return value.strip().casefold()


class MeResponse(CamelModel):
    username: str | None = None
    email: str | None = None
    email_verified: bool = False
    needs_email: bool = False
    google_linked: bool = False
    role: Literal["admin", "user"] | None = Field(
        default=None, exclude_if=lambda value: value is None
    )
    auth_required: bool = False


class LinkTokenRequest(CamelModel):
    purpose: Literal["sse", "download"]


class LinkTokenResponse(CamelModel):
    token: str
    expires_in_seconds: int
