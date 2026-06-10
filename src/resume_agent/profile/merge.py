import re

from resume_agent.models.profile import GitHubProfile, ProfileFacts, Project


_ENRICH_FIELDS = (
    "stars",
    "forks",
    "repo_url",
    "primary_language",
    "homepage_url",
    "last_updated",
)


def _norm(name: str) -> str:
    """Normalize a project name for duplicate detection."""
    return re.sub(r"[^a-z0-9]+", "", name.casefold())


def _enrich(resume_project: Project, github_project: Project) -> None:
    """Fill empty resume-project fields from its GitHub twin."""
    for field in _ENRICH_FIELDS:
        if getattr(resume_project, field) in (None, [], ""):
            value = getattr(github_project, field)
            if value is not None:
                setattr(resume_project, field, value)


def merge_facts(
    resume_facts: ProfileFacts,
    github_projects: list[Project] | None = None,
    github_profile: GitHubProfile | None = None,
) -> ProfileFacts:
    """Combine resume-derived facts with GitHub-derived facts into one ProfileFacts."""
    merged = resume_facts.model_copy(deep=True)
    if github_projects:
        by_norm = {_norm(project.name): project for project in merged.projects}
        for gh_project in github_projects:
            twin = by_norm.get(_norm(gh_project.name))
            if twin is None:
                merged.projects.append(gh_project)
            else:
                _enrich(twin, gh_project)
    if github_profile is not None:
        merged.github_profile = github_profile
    return merged
