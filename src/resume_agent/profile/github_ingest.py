from collections import Counter

from resume_agent.models.base import Source
from resume_agent.models.profile import GitHubProfile, Project


def build_github_profile(profile: dict, repos: list[dict]) -> GitHubProfile:
    """Aggregate a GitHub user profile + repo list into GitHubProfile signals."""
    languages = [r["language"] for r in repos if r.get("language")]
    top_languages = [lang for lang, _ in Counter(languages).most_common(5)]
    total_stars = sum(r.get("stargazers_count", 0) for r in repos)
    return GitHubProfile(
        username=profile.get("login"),
        bio=profile.get("bio"),
        followers=profile.get("followers"),
        public_repos=profile.get("public_repos"),
        account_created_at=profile.get("created_at"),
        top_languages=top_languages,
        total_stars=total_stars,
    )


def repo_to_project(repo: dict) -> Project:
    """Map a single GitHub repo dict into a Project fact (source=github)."""
    language = repo.get("language")
    return Project(
        source=Source.github,
        name=repo["name"],
        description=repo.get("description"),
        url=repo.get("homepage") or repo.get("html_url"),
        repo_url=repo.get("html_url"),
        stars=repo.get("stargazers_count"),
        forks=repo.get("forks_count"),
        primary_language=language,
        languages=[language] if language else [],
        topics=repo.get("topics", []),
        homepage_url=repo.get("homepage") or None,
        last_updated=repo.get("updated_at"),
        is_fork=repo.get("fork"),
    )
