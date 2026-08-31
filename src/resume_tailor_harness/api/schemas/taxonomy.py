"""Validated taxonomy edit request bodies."""

from __future__ import annotations

from pydantic import Field

from resume_tailor_harness.api.schemas.base import CamelModel


class NewDomainIn(CamelModel):
    label: str = Field(min_length=1, max_length=80)
    category: str = Field(min_length=1, max_length=40)


class MoveSkillIn(CamelModel):
    domain_id: str | None = None
    new_domain: NewDomainIn | None = None


class AddSkillIn(CamelModel):
    token: str = Field(min_length=1, max_length=100)
    domain_id: str | None = None
    new_domain: NewDomainIn | None = None


class DomainPatchIn(CamelModel):
    label: str | None = Field(default=None, min_length=1, max_length=80)
    category: str | None = None


class DomainMergeIn(CamelModel):
    into: str = Field(min_length=1)


class AliasIn(CamelModel):
    token: str = Field(min_length=1, max_length=100)
    canonical: str = Field(min_length=1, max_length=100)
