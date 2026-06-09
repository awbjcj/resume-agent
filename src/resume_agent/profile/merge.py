from resume_agent.models.profile import GitHubProfile, ProfileFacts, Project


def merge_facts(
    resume_facts: ProfileFacts,
    github_projects: list[Project] | None = None,
    github_profile: GitHubProfile | None = None,
) -> ProfileFacts:
    """Combine resume-derived facts with GitHub-derived facts into one ProfileFacts.

    Returns a copy; the resume facts are not mutated. GitHub projects are appended
    after resume projects (no dedup in v1 — the human edits facts.json).
    """
    merged = resume_facts.model_copy(deep=True)
    if github_projects:
        merged.projects = [*merged.projects, *github_projects]
    if github_profile is not None:
        merged.github_profile = github_profile
    return merged
