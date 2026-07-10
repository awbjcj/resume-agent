import httpx

from resume_agent.profile.corpus import add_source, load_manifest
from resume_agent.profile.fragments import fragment_cache_status
from resume_agent.profile.github import GitHubClient
from resume_agent.profile.github_harvest import (
    GITHUB_DOC_PREFIX,
    render_virtual_doc,
    select_repos,
    sync_github_sources,
)


def repo(name: str, **overrides) -> dict:
    value = {
        "name": name,
        "full_name": f"me/{name}",
        "html_url": f"https://github.com/me/{name}",
        "owner": {"login": "me"},
        "fork": False,
        "archived": False,
        "pushed_at": "2026-01-01T00:00:00Z",
        "stargazers_count": 1,
        "topics": ["cli"],
        "description": "a tool",
    }
    value.update(overrides)
    return value


def github(handler) -> tuple[GitHubClient, httpx.Client]:
    http = httpx.Client(
        base_url="https://api.github.com", transport=httpx.MockTransport(handler)
    )
    return GitHubClient(token="t", client=http), http


def profile(tmp_path):
    resume = tmp_path / "resume.txt"
    resume.write_text("resume", encoding="utf-8")
    profile_dir = tmp_path / "profile"
    add_source(profile_dir, resume, primary=True)
    return profile_dir


def standard_handler(repos: list[dict], readme: str = "# readme"):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/users/me/repos":
            return httpx.Response(200, json=repos)
        if path.endswith("/contents"):
            return httpx.Response(200, json=[{"name": "README.md", "type": "file"}])
        if path.endswith("/contents/README.md"):
            return httpx.Response(200, text=readme)
        if path.endswith("/languages"):
            return httpx.Response(200, json={"Python": 100})
        return httpx.Response(404)

    return handler


def test_select_repos_force_includes_before_cap_and_deny_wins():
    repos = [
        repo("keep", pushed_at="2026-03-01T00:00:00Z"),
        repo("old", pushed_at="2025-01-01T00:00:00Z"),
        repo("forked", fork=True),
        repo("dead", archived=True),
        repo("denied"),
        repo("myfork", fork=True, pushed_at="2026-02-01T00:00:00Z"),
    ]
    picked = select_repos(repos, allow=("myfork", "denied"), deny=("denied",), limit=2)
    assert [item["name"] for item in picked] == ["keep", "myfork"]


def test_render_virtual_doc_is_deterministic_sorted_and_byte_bounded():
    files = [("CONTEXT.md", "context"), ("README.md", "é" * 20_000)]
    value = repo("r", topics=["zeta", "alpha"])
    one = render_virtual_doc(value, files, {"TypeScript": 1, "Python": 9})
    two = render_virtual_doc(value, list(reversed(files)), {"Python": 9, "TypeScript": 1})
    assert one == two
    assert one.startswith("---\nrepo_url: https://github.com/me/r")
    assert one.index("Python") < one.index("TypeScript")
    assert one.index("alpha") < one.index("zeta")
    assert one.count("é") <= 15_000
    assert len(one.encode("utf-8")) <= 120_000


def test_sync_writes_registers_refreshes_stably_and_does_not_close_injected_client(tmp_path):
    profile_dir = profile(tmp_path)
    gh, http = github(standard_handler([repo("my.repo")]))
    first = sync_github_sources(profile_dir, "me", client=gh)
    assert first.written == [f"{GITHUB_DOC_PREFIX}my.repo.md"]
    document = next(doc for doc in load_manifest(profile_dir).docs if doc.origin == "github")
    assert document.mode == "project"

    again = sync_github_sources(profile_dir, "me", client=gh)
    assert again.written == []
    assert not http.is_closed

    changed_gh, changed_http = github(standard_handler([repo("my.repo")], "# changed"))
    changed = sync_github_sources(profile_dir, "me", client=changed_gh)
    refreshed = next(doc for doc in load_manifest(profile_dir).docs if doc.origin == "github")
    assert changed.written == [f"{GITHUB_DOC_PREFIX}my.repo.md"]
    assert refreshed.id == document.id
    assert fragment_cache_status(profile_dir, refreshed) == "source-changed"
    http.close()
    changed_http.close()


def test_sync_removes_delisted_or_docless_sources(tmp_path):
    profile_dir = profile(tmp_path)
    first, first_http = github(standard_handler([repo("gone")]))
    sync_github_sources(profile_dir, "me", client=first)

    empty, empty_http = github(standard_handler([]))
    report = sync_github_sources(profile_dir, "me", client=empty)
    assert report.removed == [f"{GITHUB_DOC_PREFIX}gone.md"]
    assert [doc.origin for doc in load_manifest(profile_dir).docs] == ["upload"]
    first_http.close()
    empty_http.close()


def test_dossier_supersedes_locally_even_when_remote_rate_limits(tmp_path):
    profile_dir = profile(tmp_path)
    initial, initial_http = github(standard_handler([repo("myrepo")]))
    sync_github_sources(profile_dir, "me", client=initial)

    dossier = tmp_path / "myrepo-dossier.md"
    dossier.write_text(
        "---\nrepo_url: https://github.com/me/MyRepo/\n---\n# Project: myrepo\n",
        encoding="utf-8",
    )
    add_source(profile_dir, dossier)

    limited, limited_http = github(
        lambda _request: httpx.Response(
            403,
            headers={"x-ratelimit-remaining": "0"},
            json={"message": "rate limited"},
        )
    )
    report = sync_github_sources(profile_dir, "me", client=limited)
    assert report.removed == [f"{GITHUB_DOC_PREFIX}myrepo.md"]
    assert report.superseded == [f"{GITHUB_DOC_PREFIX}myrepo.md"]
    assert any("rate limit" in warning.casefold() for warning in report.warnings)
    assert not any(doc.origin == "github" for doc in load_manifest(profile_dir).docs)
    initial_http.close()
    limited_http.close()


def test_rate_limit_and_per_repo_failure_keep_unrelated_stale_docs(tmp_path):
    profile_dir = profile(tmp_path)
    initial, initial_http = github(standard_handler([repo("cached")]))
    sync_github_sources(profile_dir, "me", client=initial)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/users/me/repos":
            return httpx.Response(200, json=[repo("bad"), repo("cached")])
        if "/repos/me/bad/" in request.url.path:
            return httpx.Response(500)
        return httpx.Response(
            403,
            headers={"x-ratelimit-remaining": "0"},
            json={"message": "rate limited"},
        )

    failing, failing_http = github(handler)
    report = sync_github_sources(profile_dir, "me", client=failing)
    assert "bad" in report.failures
    assert report.removed == []
    assert any(doc.origin == "github" for doc in load_manifest(profile_dir).docs)
    initial_http.close()
    failing_http.close()
