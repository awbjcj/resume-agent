from pydantic import Field

from resume_agent.models.base import ExtensibleModel


class MatchPlanRequirement(ExtensibleModel):
    """One JD requirement mapped to supporting profile fact ids."""

    jd_requirement: str
    supporting_fact_ids: list[str] = Field(default_factory=list)
    emphasis: str = ""
    gap: bool = False


class MatchPlan(ExtensibleModel):
    """Transient pre-draft strategy; it is not a source of candidate facts."""

    requirements: list[MatchPlanRequirement] = Field(default_factory=list)
