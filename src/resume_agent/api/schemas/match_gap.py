"""Match-gap API schemas for the skill-demand graph."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from resume_agent.api.schemas.base import CamelModel
from resume_agent.tracking.match_gap import normalize_skill


class RefreshClustersIn(CamelModel):
    """Exact visible canonical keys to regroup, bounded at the API boundary."""

    skill_keys: list[str] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def normalize_and_dedupe(self) -> "RefreshClustersIn":
        normalized = list(
            dict.fromkeys(
                token for raw in self.skill_keys if (token := normalize_skill(raw))
            )
        )
        if not normalized:
            raise ValueError("skillKeys must include at least one usable skill key")
        self.skill_keys = normalized
        return self


class RestoreSkillsIn(RefreshClustersIn):
    """Retired keys to return to the backlog; same bounds as a scoped regroup."""


class RestoreSkillsOut(CamelModel):
    restored: int
    restored_skills: list[str]


class RetiredSkillOut(CamelModel):
    key: str
    reason: str
    retired_at: datetime


class GroupingStatusOut(CamelModel):
    state: Literal["uncertain", "failed"]
    reason: str
    last_attempted_at: datetime


class JobLiteOut(CamelModel):
    id: int
    company: str | None = None
    title: str | None = None
    seniority: str | None = None
    status: str


class SkillNodeOut(CamelModel):
    skill: str
    domain_id: str | None = None
    covered: bool
    coverage: Literal["covered", "adjacent", "gap"] = "gap"
    key: str
    members: dict[str, int]
    must: int
    nice: int
    tech: int
    job_count: int
    grouping_status: GroupingStatusOut | None = None

    @model_validator(mode="after")
    def sync_legacy_covered(self) -> "SkillNodeOut":
        if self.covered or self.coverage == "covered":
            self.covered = True
            self.coverage = "covered"
        else:
            self.covered = False
        return self


class DemandEdgeOut(CamelModel):
    job_id: int
    skill: str
    source: Literal["must", "nice", "tech"]
    skill_key: str


class DomainOut(CamelModel):
    id: str
    label: str
    category: str
    essential_score: int
    popular_score: int
    job_count: int
    skill_count: int
    gap_count: int
    adjacent_count: int = 0


class SuggestionStatusOut(CamelModel):
    kind: Literal["skill", "domain"]
    key: str
    state: Literal["ready", "stale"]
    generated_at: datetime


class CategoryOut(CamelModel):
    slug: str
    label: str
    kind: Literal["hard", "soft"]


class TaxonomyManifestOut(CamelModel):
    generated: str = ""
    corrections: str = ""
    state: str = ""
    overrides: str = ""
    semantic: str = ""


class OverrideConflictOut(CamelModel):
    token: str
    correction_head: str
    override_head: str
    resolution: Literal["override", "forbid_alias"]


class MatchGapOut(CamelModel):
    target_total: int
    clusters_stale: bool
    jobs: list[JobLiteOut]
    skills: list[SkillNodeOut]
    edges: list[DemandEdgeOut]
    domains: list[DomainOut]
    categories: list[CategoryOut]
    suggestion_statuses: list[SuggestionStatusOut] = Field(default_factory=list)
    taxonomy_generation: str | None = None
    taxonomy_algorithm_version: str = "legacy"
    taxonomy_maintenance_due: bool = True
    unassigned_count: int = 0
    taxonomy_undo_available: bool = False
    taxonomy_revision: str = ""
    taxonomy_manifest: TaxonomyManifestOut | None = None
    override_conflicts: list[OverrideConflictOut] = Field(default_factory=list)
    # Tokens the classifier judged to name no skill.  They are excluded from the
    # backlog, so they must stay visible somewhere or a wrong call is invisible
    # and irreversible.
    retired_skills: list[RetiredSkillOut] = Field(default_factory=list)
