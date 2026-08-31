from typing import Literal

from pydantic import EmailStr, Field, field_validator

from resume_tailor_harness.api.schemas.base import CamelModel


class EmailBody(CamelModel):
    email: EmailStr

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().casefold()


class RegisterRequest(EmailBody):
    password: str = Field(min_length=1, max_length=1024)
    invite_code: str = Field(default="", pattern=r"^(?:.{8,128})?$")
    display_name: str | None = Field(default=None, max_length=64)

    @field_validator("invite_code", mode="before")
    @classmethod
    def normalize_optional_invite(cls, value: str) -> str:
        return value.strip()


class VerifyEmailRequest(EmailBody):
    code: str = Field(pattern=r"^\d{6}$")


class ResendCodeRequest(EmailBody):
    pass


class ForgotPasswordRequest(EmailBody):
    pass


class ResetPasswordRequest(EmailBody):
    code: str = Field(pattern=r"^\d{6}$")
    new_password: str = Field(min_length=1, max_length=1024)


class CodeSentResponse(CamelModel):
    status: Literal["sent"] = "sent"
