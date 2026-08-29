from resume_agent.models.profile import GitHubProfile, Project
from resume_agent.profile.github_ingest import (
    build_github_profile,
    normalize_repo_url,
    repo_to_project,
)


def test_build_github_profile_aggregates_signals():
    profile = {
        "login": "ada",
        "bio": "math",
        "followers": 42,
        "public_repos": 2,
        "created_at": "2010-01-01T00:00:00Z",
    }
    repos = [
        {"language": "Python", "stargazers_count": 10},
        {"language": "Python", "stargazers_count": 5},
        {"language": "Rust", "stargazers_count": 1},
    ]
    gh = build_github_profile(profile, repos)
    assert isinstance(gh, GitHubProfile)
    assert gh.username == "ada"
    assert gh.total_stars == 16
    assert gh.top_languages[0] == "Python"
    assert gh.source.value == "github"


def test_repo_to_project_maps_metadata():
    repo = {
        "name": "engine",
        "description": "the first computer",
        "html_url": "https://github.com/ada/engine",
        "homepage": "https://ada.dev",
        "stargazers_count": 10,
        "forks_count": 2,
        "language": "Python",
        "topics": ["compute"],
        "updated_at": "2024-01-01T00:00:00Z",
        "fork": False,
    }
    proj = repo_to_project(repo)
    assert isinstance(proj, Project)
    assert proj.source.value == "github"
    assert proj.name == "engine"
    assert proj.repo_url == "https://github.com/ada/engine"
    assert proj.url == "https://ada.dev"
    assert proj.stars == 10
    assert proj.primary_language == "Python"
    assert proj.topics == ["compute"]
    assert proj.is_fork is False


def test_repo_to_project_falls_back_to_html_url_when_no_homepage():
    repo = {"name": "x", "html_url": "https://github.com/ada/x"}
    proj = repo_to_project(repo)
    assert proj.url == "https://github.com/ada/x"
    assert proj.languages == []


def test_repo_to_project_uses_byte_weighted_languages():
    repo = {
        "name": "x",
        "html_url": "https://github.com/ada/x",
        "language": "TypeScript",
    }
    project = repo_to_project(repo, languages={"TypeScript": 100, "Python": 9000})
    assert project.languages == ["Python", "TypeScript"]


def test_normalize_repo_url_unifies_https_and_ssh_remotes():
    expected = "github.com/me/repo"
    assert normalize_repo_url("HTTPS://GitHub.com/Me/Repo.git/") == expected
    assert normalize_repo_url("git@github.com:Me/Repo.git") == expected
    assert normalize_repo_url("ssh://git@github.com/Me/Repo.git") == expected
    assert normalize_repo_url(None) is None
    assert normalize_repo_url(" ") is None
