"""Setup readiness projection for the first-run gate + dashboard health card."""

from __future__ import annotations

from resume_agent.api.schemas.base import CamelModel


class SecretsStatus(CamelModel):
    anthropic_key: bool
    any_llm_key: bool


class ProfileStatus(CamelModel):
    document_count: int
    has_resume: bool
    facts_built_at: str | None = None
    github_username: str | None = None


class SearchStatus(CamelModel):
    configured: bool


class SourcesStatus(CamelModel):
    enabled_count: int


class SetupStatusOut(CamelModel):
    secrets: SecretsStatus
    profile: ProfileStatus
    search: SearchStatus
    sources: SourcesStatus
    complete: bool
