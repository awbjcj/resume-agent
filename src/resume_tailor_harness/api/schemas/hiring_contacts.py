"""Job-scoped hiring-contact intelligence API contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from resume_tailor_harness.api.schemas.base import CamelModel
from resume_tailor_harness.hiring_contacts.models import (
    HiringContactIntelligence,
    HiringContactType,
    HiringContactVerification,
)


class HiringContactOut(CamelModel):
    name: str
    public_role: str
    contact_type: HiringContactType
    source_urls: list[str] = Field(default_factory=list)
    verification_state: HiringContactVerification
    why_relevant: str
    email_draft: str
    short_message_draft: str


class HiringContactIntelligenceOut(CamelModel):
    job_id: int
    company: str
    title: str
    retrieved_at: datetime
    contacts: list[HiringContactOut] = Field(default_factory=list)
    generic_email_draft: str
    generic_short_message_draft: str
    caveat: str

    @classmethod
    def from_artifact(
        cls, artifact: HiringContactIntelligence
    ) -> HiringContactIntelligenceOut:
        return cls.model_validate(artifact.model_dump())


class HiringContactBaseOut(CamelModel):
    message: str | None = None


class HiringContactUnavailableOut(HiringContactBaseOut):
    state: Literal["unavailable"] = "unavailable"
    reason: Literal["missing_company"] = "missing_company"
    can_refresh: Literal[False] = False
    intelligence: None = None


class HiringContactEmptyOut(HiringContactBaseOut):
    state: Literal["empty"] = "empty"
    reason: Literal["not_generated"] = "not_generated"
    can_refresh: Literal[True] = True
    intelligence: None = None


class HiringContactReadyOut(HiringContactBaseOut):
    state: Literal["ready"] = "ready"
    reason: None = None
    can_refresh: Literal[True] = True
    intelligence: HiringContactIntelligenceOut


HiringContactResourceOut = Annotated[
    HiringContactUnavailableOut | HiringContactEmptyOut | HiringContactReadyOut,
    Field(discriminator="state"),
]
