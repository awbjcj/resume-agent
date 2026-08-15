from resume_agent.models.resume import ResumeContent
from resume_agent.tailor.review_config import LengthBudget


def format_budget(budget: LengthBudget) -> str:
    """Render the budget as one prompt instruction for tailor/reviser agents.

    The prose caps and the skills target are stated as two separate budgets on
    purpose. Given only caps and "drop the rest", the writer economized on the
    skills section as hard as on bullets, even though the two cost wildly
    different amounts of page space - so the skills sentence has to say what it
    actually costs, or the one-page instruction reads as a reason to cut it.
    """
    return (
        f"Target a single page. Use at most {budget.max_experiences} experiences, "
        f"{budget.max_projects} projects, and {budget.max_evidence_owners} combined "
        f"evidence owners; at most {budget.max_bullets_per_role} bullets per role, "
        f"{budget.max_bullets_per_project} bullets per project, and about "
        f"{budget.target_total_bullets} bullets in total. Prefer the most relevant facts; "
        "drop the rest. "
        "The skills section is budgeted separately and is not where a resume runs "
        f"long: it renders as one comma-joined line per category, so about "
        f"{budget.target_skills} entries cost roughly five lines. Aim for "
        f"{budget.target_skills} skills entries, at most "
        f"{budget.max_skills_per_category} per category, and include every profile "
        "skill this job names as well as every adjacent skill from the same stack, "
        "toolchain, or domain. Listing an adjacent skill under its own true name "
        "from the cited fact is correct and expected; renaming it to the job's own "
        "term is not, and still fails. Cut only skills genuinely irrelevant to this "
        "role; do not drop a relevant skill to save space."
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
