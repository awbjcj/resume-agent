"""Advisory measurement of whether a resume rendered planned evidence depth."""

from typing import cast

from pydantic import Field

from resume_agent.models.base import ExtensibleModel
from resume_agent.models.profile import ProfileFacts
from resume_agent.models.resume import ResumeContent
from resume_agent.models.review import ReviewCritique, ReviewIssue, Severity
from resume_agent.profile.aspects import ASPECTS, Aspect
from resume_agent.profile.depth import OwnerKind, OwnerRef, planned_owners
from resume_agent.tailor.length import clamped_floor
from resume_agent.tailor.review_config import LengthBudget


DEPTH_REVIEWER = "bullet-depth"


class DepthCritique(ReviewCritique):
    """Runtime marker for advisory depth measurement, never a deterministic gate."""

    owners_total: int = 0
    owners_met: int = 0


class OwnerDepth(ExtensibleModel):
    id: str
    kind: OwnerKind
    label: str
    floor: int
    rendered: int
    aspects_rendered: list[Aspect] = Field(default_factory=list)
    absent: bool = False


class DepthReport(ExtensibleModel):
    owners: list[OwnerDepth] = Field(default_factory=list)


def _rendered_counts(content: ResumeContent) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in (*content.experience, *content.projects):
        counts[entry.provenance] = counts.get(entry.provenance, 0) + len(entry.bullets)
    return counts


def _rendered_aspects(content: ResumeContent, owner: OwnerRef) -> list[Aspect]:
    by_id = {bullet.id: bullet.aspect for bullet in owner.bullets}
    found: list[Aspect] = []
    for entry in (*content.experience, *content.projects):
        if entry.provenance != owner.id:
            continue
        for bullet in entry.bullets:
            aspect = by_id.get(bullet.provenance)
            if aspect in ASPECTS and aspect not in found:
                found.append(cast(Aspect, aspect))
    return found


def depth_report(
    content: ResumeContent, facts: ProfileFacts, budget: LengthBudget
) -> DepthReport:
    """Per selected owner: rendered count, floor, and cited-aspect spread."""
    counts = _rendered_counts(content)
    return DepthReport(
        owners=[
            OwnerDepth(
                id=owner.id,
                kind=owner.kind,
                label=owner.label,
                floor=clamped_floor(owner, budget),
                rendered=counts.get(owner.id, 0),
                aspects_rendered=_rendered_aspects(content, owner),
                absent=owner.id not in counts,
            )
            for owner in planned_owners(facts, budget)
        ]
    )


def _issues(report: DepthReport, budget: LengthBudget) -> list[ReviewIssue]:
    issues: list[ReviewIssue] = []
    for owner in report.owners:
        location = f"{owner.kind}/{owner.id}"
        if owner.absent:
            issues.append(
                ReviewIssue(
                    severity=Severity.major,
                    location=location,
                    message=(
                        f"{owner.label!r} ({owner.id}) is absent from this resume "
                        "despite being in the BULLET DEPTH PLAN"
                    ),
                    suggestion=(
                        "add the owner and render its cited facts up to the stated "
                        "supply-clamped range"
                    ),
                )
            )
            continue
        if owner.rendered < owner.floor:
            issues.append(
                ReviewIssue(
                    severity=Severity.major,
                    location=location,
                    message=(
                        f"{owner.label!r} ({owner.id}) rendered {owner.rendered} "
                        f"bullets against its supply-clamped floor of {owner.floor}"
                    ),
                    suggestion="add remaining cited facts for this owner",
                )
            )
        if owner.rendered >= 3 and len(owner.aspects_rendered) == 1:
            issues.append(
                ReviewIssue(
                    severity=Severity.minor,
                    location=location,
                    message=(
                        f"{owner.label!r} ({owner.id}) rendered {owner.rendered} "
                        f"bullets under only one aspect ({owner.aspects_rendered[0]})"
                    ),
                    suggestion=(
                        f"use cited facts spanning at least {budget.min_aspects_per_owner} "
                        "different aspects when source supply permits"
                    ),
                )
            )
    return issues


def depth_critique(
    content: ResumeContent, facts: ProfileFacts, budget: LengthBudget
) -> DepthCritique | None:
    """Return advisory depth feedback, or no measurement when no owner is planned."""
    report = depth_report(content, facts, budget)
    if not report.owners:
        return None
    owners_met = sum(
        not owner.absent and owner.rendered >= owner.floor for owner in report.owners
    )
    return DepthCritique(
        reviewer=DEPTH_REVIEWER,
        score=round(100 * owners_met / len(report.owners)),
        passed=True,
        owners_total=len(report.owners),
        owners_met=owners_met,
        issues=_issues(report, budget),
    )
