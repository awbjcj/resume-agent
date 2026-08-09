from resume_agent.models.evidence_portfolio import EvidencePortfolio
from resume_agent.models.resume import ResumeContent
from resume_agent.models.review import ReviewCritique, ReviewIssue, Severity
from resume_agent.tracking.match_gap import normalize_skill


PORTFOLIO_ALIGNMENT_REVIEWER = "portfolio-alignment"


def _contains(text: str, terms: set[str]) -> bool:
    normalized = f" {normalize_skill(text)} "
    return any(f" {term} " in normalized for term in terms if term)


def portfolio_alignment_critique(
    content: ResumeContent, portfolio: EvidencePortfolio | None
) -> ReviewCritique | None:
    """Measure whether planned core skills reached both resume channels.

    This is advisory: a one-page layout can force a truthful cut. The critique
    still gives the reviser precise major issues and a deterministic score.
    """
    if portfolio is None:
        return None
    core = [
        requirement
        for requirement in portfolio.requirements
        if requirement.kind == "skill"
        and requirement.core
        and requirement.coverage == "covered"
    ][:5]
    if not core:
        return None

    skill_names = [
        skill.name for entries in content.skills.values() for skill in entries
    ]
    prose = [
        bullet.text
        for experience in content.experience
        for bullet in experience.bullets
    ] + [
        bullet.text for project in content.projects for bullet in project.bullets
    ]
    selected_context_ids = {
        fact_id
        for selection in portfolio.selections
        for fact_id in selection.selected_fact_ids
        if fact_id not in portfolio.selected_skill_fact_ids
    }
    issues: list[ReviewIssue] = []
    earned = 0
    possible = 0
    for requirement in core:
        terms = {
            normalize_skill(term)
            for term in [requirement.text, *requirement.approved_terms]
            if normalize_skill(term)
        }
        possible += 1
        if any(_contains(name, terms) for name in skill_names):
            earned += 1
        else:
            issues.append(
                ReviewIssue(
                    severity=Severity.major,
                    location="skills",
                    message=(
                        f"core skill {requirement.text!r} is absent from the skills section"
                    ),
                    suggestion="add the approved skill term with its selected skill fact id",
                )
            )

        contextual_available = bool(
            selected_context_ids & set(requirement.supporting_fact_ids)
        )
        if contextual_available:
            possible += 1
            if any(_contains(text, terms) for text in prose):
                earned += 1
            else:
                issues.append(
                    ReviewIssue(
                        severity=Severity.major,
                        location="experience/projects",
                        message=(
                            f"core skill {requirement.text!r} has selected evidence but "
                            "is absent from contextual resume prose"
                        ),
                        suggestion=(
                            "use an approved term in a bullet whose cited fact supports it"
                        ),
                    )
                )
    return ReviewCritique(
        reviewer=PORTFOLIO_ALIGNMENT_REVIEWER,
        score=round(100 * earned / possible) if possible else 100,
        passed=True,
        issues=issues,
    )

