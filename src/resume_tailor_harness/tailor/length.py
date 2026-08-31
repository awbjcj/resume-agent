from resume_tailor_harness.models.resume import ResumeContent
from resume_tailor_harness.profile.depth import clamped_ceiling, clamped_floor, planned_owners
from resume_tailor_harness.models.profile import ProfileFacts
from resume_tailor_harness.tailor.review_config import LengthBudget


def format_budget(budget: LengthBudget) -> str:
    """Render the budget as one prompt instruction for tailor/reviser agents.

    The prose ranges and the skills target are stated as two separate budgets on
    purpose. Given only caps and "drop the rest", the writer economized on the
    skills section as hard as on bullets, even though the two cost wildly
    different amounts of page space - so the skills sentence has to say what it
    actually costs, or the one-page instruction reads as a reason to cut it.
    """
    return (
        f"Target {budget.page_target} pages. Use at most {budget.max_experiences} experiences, "
        f"{budget.max_projects} projects, and {budget.max_evidence_owners} combined "
        f"evidence owners; roles render {budget.min_bullets_per_role}–"
        f"{budget.max_bullets_per_role} bullets and projects render "
        f"{budget.min_bullets_per_project}–{budget.max_bullets_per_project}, "
        f"subject to the per-owner depth plan. Aim for about "
        f"{budget.target_total_bullets} bullets in total. Within each owner, "
        f"cover at least {budget.min_aspects_per_owner} different aspects when "
        "the cited source supply permits it. "
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


def format_depth_plan(facts: ProfileFacts, budget: LengthBudget) -> str:
    """Deterministic, fact-clamped render ranges for the selected owners."""
    owners = planned_owners(facts, budget)
    if not owners:
        return ""
    lines = ["BULLET DEPTH PLAN (deterministic; per evidence owner):"]
    for owner in owners:
        supply = len(owner.bullets)
        floor = clamped_floor(owner, budget)
        ceiling = clamped_ceiling(owner, budget)
        span = str(floor) if floor == ceiling else f"{floor}–{ceiling}"
        limited = supply < (
            budget.min_bullets_per_role
            if owner.kind == "experience"
            else budget.min_bullets_per_project
        )
        note = " (supply-limited; do not invent)" if limited else ""
        lines.append(
            f'- {owner.id} "{owner.label}": {supply} source -> render {span}{note}'
        )
    return "\n".join(lines)


def resume_stats(content: ResumeContent) -> str:
    """Deterministic size summary for reviewers."""
    total_bullets = sum(len(e.bullets) for e in content.experience) + sum(
        len(p.bullets) for p in content.projects
    )
    return (
        f"experiences={len(content.experience)} projects={len(content.projects)} "
        f"total_bullets={total_bullets}"
    )
