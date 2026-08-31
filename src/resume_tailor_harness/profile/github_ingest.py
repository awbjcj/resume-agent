from collections import Counter
import re
from urllib.parse import urlsplit

from resume_tailor_harness.models.base import Source
from resume_tailor_harness.models.profile import GitHubProfile, Project


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


_SCP_REMOTE = re.compile(r"^(?:[^@\s]+@)?([^:\s]+):(.+)$")


def normalize_repo_url(url: str | None) -> str | None:
    """Normalize equivalent HTTPS/SSH repository remotes to host/path."""
    if not url or not url.strip():
        return None
    value = url.strip().rstrip("/")
    match = _SCP_REMOTE.match(value) if "://" not in value else None
    if match is not None:
        host, path = match.groups()
    else:
        parsed = urlsplit(value)
        if not parsed.hostname:
            return None
        host, path = parsed.hostname, parsed.path
    normalized_path = path.strip("/")
    if normalized_path.casefold().endswith(".git"):
        normalized_path = normalized_path[:-4]
    if not normalized_path:
        return None
    return f"{host.casefold()}/{normalized_path.casefold()}"


def repo_to_project(repo: dict, languages: dict[str, int] | None = None) -> Project:
    """Map a single GitHub repo dict into a Project fact (source=github)."""
    language = repo.get("language")
    ordered_languages = (
        [
            name
            for name, _count in sorted(
                languages.items(), key=lambda item: (-item[1], item[0].casefold())
            )
        ]
        if languages
        else ([language] if language else [])
    )
    return Project(
        source=Source.github,
        name=repo["name"],
        description=repo.get("description"),
        url=repo.get("homepage") or repo.get("html_url"),
        repo_url=repo.get("html_url"),
        stars=repo.get("stargazers_count"),
        forks=repo.get("forks_count"),
        primary_language=language,
        languages=ordered_languages,
        topics=repo.get("topics", []),
        homepage_url=repo.get("homepage") or None,
        last_updated=repo.get("updated_at"),
        is_fork=repo.get("fork"),
    )
