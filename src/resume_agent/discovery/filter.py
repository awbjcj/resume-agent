from pydantic import Field

from resume_agent.discovery.search_config import SearchConfig
from resume_agent.models.base import ExtensibleModel
from resume_agent.models.job import JobCriteria, SponsorshipSignal


class FilterDecision(ExtensibleModel):
    keep: bool
    reject_reason: str | None = None
    flags: list[str] = Field(default_factory=list)


def apply_filters(criteria: JobCriteria, config: SearchConfig) -> FilterDecision:
    """Deterministic hard filter. Sponsorship 'silent' is kept but flagged."""
    flags: list[str] = []

    if config.sponsorship_required:
        if criteria.sponsorship_signal == SponsorshipSignal.denied:
            return FilterDecision(keep=False, reject_reason="sponsorship not available")
        if criteria.sponsorship_signal == SponsorshipSignal.silent:
            flags.append("sponsorship_uncertain")

    if (
        config.min_salary is not None
        and criteria.salary_range is not None
        and criteria.salary_range.maximum is not None
        and criteria.salary_range.maximum < config.min_salary
    ):
        return FilterDecision(keep=False, reject_reason="salary below minimum")

    if (
        config.yoe_max is not None
        and criteria.yoe_min is not None
        and criteria.yoe_min > config.yoe_max
    ):
        return FilterDecision(
            keep=False, reject_reason="requires more experience than yoe_max"
        )

    return FilterDecision(keep=True, flags=flags)
