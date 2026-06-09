from pathlib import Path

from resume_agent.models.profile import ProfileFacts
from resume_agent.profile.extractor import build_extractor_agent, extract_profile_facts
from resume_agent.profile.github import GitHubClient
from resume_agent.profile.github_ingest import build_github_profile, repo_to_project
from resume_agent.profile.merge import merge_facts
from resume_agent.profile.resume_reader import read_resume_text


def build_profile(
    resume_path: str | Path,
    github_username: str | None,
    extractor_agent=None,
    github_client=None,
) -> ProfileFacts:
    """Build a merged ProfileFacts from a resume file and (optionally) GitHub.

    ``extractor_agent`` and ``github_client`` are injectable for testing; in
    normal use they default to the real Agno agent and GitHub REST client.
    """
    text = read_resume_text(resume_path)
    agent = extractor_agent if extractor_agent is not None else build_extractor_agent()
    resume_facts = extract_profile_facts(text, agent)

    if not github_username:
        return merge_facts(resume_facts)

    gh = github_client if github_client is not None else GitHubClient()
    profile_data = gh.fetch_profile(github_username)
    repos = gh.fetch_repos(github_username)
    gh_profile = build_github_profile(profile_data, repos)
    projects = [repo_to_project(repo) for repo in repos]
    return merge_facts(resume_facts, github_projects=projects, github_profile=gh_profile)
