from evals.schema import Trap
from evals.textscan import trap_terms_hit
from resume_agent.models.profile import ProfileFacts
from resume_agent.models.resume import ResumeContent
from resume_agent.tailor.provenance import check_provenance, referenced_ids
from resume_agent.tailor.review_config import LengthBudget


def trap_avoided(content: ResumeContent, traps: list[Trap]) -> bool:
    return not trap_terms_hit(content, traps)


def provenance_ok(content: ResumeContent, facts: ProfileFacts) -> bool:
    return check_provenance(content, facts).ok


def must_cite_covered(content: ResumeContent, must_cite: list[str]) -> bool:
    cited = referenced_ids(content)
    return all(fact_id in cited for fact_id in must_cite)


def budget_ok(content: ResumeContent, budget: LengthBudget) -> bool:
    if len(content.experience) > budget.max_experiences:
        return False
    return not any(
        len(experience.bullets) > budget.max_bullets_per_role
        for experience in content.experience
    )


def total_bullets(content: ResumeContent) -> int:
    return (
        sum(len(experience.bullets) for experience in content.experience)
        + sum(len(project.bullets) for project in content.projects)
        + sum(len(volunteer.bullets) for volunteer in content.volunteer)
    )
