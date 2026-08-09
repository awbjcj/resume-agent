from resume_agent.models.resume import ResumeContent
from resume_agent.tailor.review_config import LengthBudget


def format_budget(budget: LengthBudget) -> str:
    """Render the budget as one prompt instruction for tailor/reviser agents."""
    return (
        f"Target a single page. Use at most {budget.max_experiences} experiences, "
        f"{budget.max_projects} projects, and {budget.max_evidence_owners} combined "
        f"evidence owners; at most {budget.max_bullets_per_role} bullets per role, "
        f"{budget.max_bullets_per_project} bullets per project, and about "
        f"{budget.target_total_bullets} bullets in total. Prefer the most relevant facts; "
        "drop the rest."
    )


def resume_stats(content: ResumeContent) -> str:
    """Deterministic size summary for reviewers."""
    total_bullets = sum(len(e.bullets) for e in content.experience) + sum(
        len(p.bullets) for p in content.projects
    )
    return (
        f"experiences={len(content.experience)} projects={len(content.projects)} "
        f"total_bullets={total_bullets}"
    )
