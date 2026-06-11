from resume_agent.llm_runner import Runner
from resume_agent.models.job import JobCriteria
from resume_agent.models.profile import ProfileFacts
from resume_agent.models.resume import ResumeContent
from resume_agent.models.review import ReviewCritique
from resume_agent.tailor.length import format_budget
from resume_agent.tailor.review_config import LengthBudget


def compose_tailor_input(
    jd_text: str,
    criteria: JobCriteria,
    profile_facts: ProfileFacts,
    length_budget: LengthBudget | None = None,
) -> str:
    budget_line = f"\n\nLENGTH BUDGET:\n{format_budget(length_budget)}" if length_budget else ""
    return (
        "CANDIDATE PROFILE (JSON):\n"
        f"{profile_facts.model_dump_json()}\n\n"
        "JOB CRITERIA (JSON):\n"
        f"{criteria.model_dump_json()}\n\n"
        "JOB DESCRIPTION:\n"
        f"{jd_text}"
        f"{budget_line}"
    )


def tailor(input_text: str, agent: Runner) -> ResumeContent:
    result = agent.run(input_text)
    content = result.content
    if not isinstance(content, ResumeContent):
        raise TypeError(f"Expected ResumeContent from tailor agent, got {type(content).__name__}")
    return content


def compose_revise_input(
    content: ResumeContent,
    critiques: list[ReviewCritique],
    profile_facts: ProfileFacts,
    length_budget: LengthBudget | None = None,
) -> str:
    issues = "\n".join(
        f"- [{c.reviewer}] {issue.severity.value}: {issue.message}"
        + (f" (suggestion: {issue.suggestion})" if issue.suggestion else "")
        for c in critiques
        for issue in c.issues
    )
    suggestions = "\n".join(
        f"- [{c.reviewer}] {suggestion}"
        for c in critiques
        for suggestion in c.suggestions
    )
    budget_line = f"\n\nLENGTH BUDGET:\n{format_budget(length_budget)}" if length_budget else ""
    return (
        "CANDIDATE PROFILE (JSON):\n"
        f"{profile_facts.model_dump_json()}\n\n"
        "CURRENT RESUME (JSON):\n"
        f"{content.model_dump_json()}\n\n"
        "REVIEWER ISSUES:\n"
        f"{issues}\n\n"
        "REVIEWER SUGGESTIONS:\n"
        f"{suggestions}"
        f"{budget_line}"
    )


def revise(input_text: str, agent: Runner) -> ResumeContent:
    result = agent.run(input_text)
    content = result.content
    if not isinstance(content, ResumeContent):
        raise TypeError(f"Expected ResumeContent from reviser agent, got {type(content).__name__}")
    return content
