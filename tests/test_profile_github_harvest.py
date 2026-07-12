import httpx

from resume_agent.profile.corpus import add_source, load_manifest
from resume_agent.profile.fragments import fragment_cache_status
from resume_agent.profile.github import GitHubClient
from resume_agent.profile.github_harvest import (
    GITHUB_DOC_PREFIX,
    _dossier_filename,
    _github_docs_for,
    _pick_doc_entries,
    _pick_dossier_entries,
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


DOSSIER = "---\nrepo_url: https://github.com/me/{repo}\n---\n# Project: {name}\n"


def mono_handler(repos: list[dict], files: dict[str, str]):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/users/me/repos":
            return httpx.Response(200, json=repos)
        if path.endswith("/contents"):
            return httpx.Response(
                200, json=[{"name": name, "type": "file"} for name in files]
            )
        for name, text in files.items():
            if path.endswith(f"/contents/{name.replace(' ', '%20')}") or path.endswith(
                f"/contents/{name}"
            ):
                return httpx.Response(200, text=text)
        if path.endswith("/languages"):
            return httpx.Response(200, json={"Python": 100})
        return httpx.Response(404)

    return handler


def dossier(repo_name: str, project: str) -> str:
    return DOSSIER.format(repo=repo_name, name=project)


def listing(*names: str) -> list[dict]:
    return [{"name": name, "type": "file"} for name in names]


def test_pick_dossier_entries_matches_caps_and_sorts():
    selected, overflow = _pick_dossier_entries(
        listing(
            "README.md",
            "zeta-dossier.md",
            "Alpha-Dossier.md",
            "dossier-notes.md",
            "b-dossier.md",
            "c-dossier.md",
            "d-dossier.md",
            "dossier.txt",
            "CHANGELOG.md",
        )
    )
    assert selected == [
        "Alpha-Dossier.md",
        "b-dossier.md",
        "c-dossier.md",
        "d-dossier.md",
        "dossier-notes.md",
    ]
    assert overflow == ["zeta-dossier.md"]


def test_pick_dossier_entries_ignores_directories():
    selected, overflow = _pick_dossier_entries(
        [{"name": "x-dossier.md", "type": "dir"}]
    )
    assert selected == [] and overflow == []


def test_pick_doc_entries_keeps_existing_readme_fallback_behavior():
    names = _pick_doc_entries(listing("README.md", "readme-dossier.md", "claude.md"))
    assert names == ["readme-dossier.md", "README.md", "claude.md"]


def test_dossier_filename_slugs_and_dodges_upload_conflicts(tmp_path):
    profile_dir = profile(tmp_path)
    value = repo("My.Repo")
    assert (
        _dossier_filename(value, "API Gateway-dossier.md", profile_dir)
        == "github--my.repo--api-gateway-dossier.md"
    )
    conflict = tmp_path / "github--my.repo--api-gateway-dossier.md"
    conflict.write_text("upload", encoding="utf-8")
    add_source(profile_dir, conflict)
    resolved = _dossier_filename(value, "API Gateway-dossier.md", profile_dir)
    assert resolved.startswith("github--my.repo--api-gateway-dossier-")
    assert resolved != "github--my.repo--api-gateway-dossier.md"


def test_dossier_filename_keeps_sanitized_stem_collisions_distinct(tmp_path):
    profile_dir = profile(tmp_path)
    value = repo("mono")
    first = _dossier_filename(
        value, "api dossier.md", profile_dir, force_suffix=True
    )
    second = _dossier_filename(
        value, "api-dossier.md", profile_dir, force_suffix=True
    )
    assert first.startswith(f"{GITHUB_DOC_PREFIX}mono--api-dossier-")
    assert second.startswith(f"{GITHUB_DOC_PREFIX}mono--api-dossier-")
    assert second != first
    upper = _dossier_filename(value, "API-Dossier.md", profile_dir, force_suffix=True)
    lower = _dossier_filename(value, "api-dossier.md", profile_dir, force_suffix=True)
    assert upper != lower


def test_github_docs_for_matches_by_frontmatter_url(tmp_path):
    profile_dir = profile(tmp_path)
    gh, http = github(standard_handler([repo("mine"), repo("other")]))
    sync_github_sources(profile_dir, "me", client=gh)
    http.close()
    assert _github_docs_for(profile_dir, "github.com/me/mine") == {
        f"{GITHUB_DOC_PREFIX}mine.md"
    }
    assert _github_docs_for(profile_dir, None) == set()


def test_dossiers_replace_readme_doc_and_yield_one_doc_each(tmp_path):
    profile_dir = profile(tmp_path)
    plain, plain_http = github(standard_handler([repo("mono")]))
    sync_github_sources(profile_dir, "me", client=plain)
    plain_http.close()

    gh, http = github(
        mono_handler(
            [repo("mono")],
            {
                "README.md": "# readme",
                "api-dossier.md": dossier("mono", "API Gateway"),
                "ui-dossier.md": dossier("mono", "UI Dashboard"),
            },
        )
    )
    report = sync_github_sources(profile_dir, "me", client=gh)
    filenames = {
        doc.filename for doc in load_manifest(profile_dir).docs if doc.origin == "github"
    }
    assert filenames == {
        f"{GITHUB_DOC_PREFIX}mono--api-dossier.md",
        f"{GITHUB_DOC_PREFIX}mono--ui-dossier.md",
    }
    assert f"{GITHUB_DOC_PREFIX}mono.md" in report.removed
    docs = [doc for doc in load_manifest(profile_dir).docs if doc.origin == "github"]
    assert all(doc.mode == "project" for doc in docs)
    assert "me/mono" in report.languages

    again = sync_github_sources(profile_dir, "me", client=gh)
    assert again.written == []
    http.close()


def test_dossier_without_frontmatter_falls_back_to_readme(tmp_path):
    profile_dir = profile(tmp_path)
    gh, http = github(
        mono_handler(
            [repo("mono")],
            {"README.md": "# readme", "notes-dossier.md": "# just notes"},
        )
    )
    sync_github_sources(profile_dir, "me", client=gh)
    filenames = {
        doc.filename for doc in load_manifest(profile_dir).docs if doc.origin == "github"
    }
    assert filenames == {f"{GITHUB_DOC_PREFIX}mono.md"}
    content = (
        profile_dir / "sources" / f"{GITHUB_DOC_PREFIX}mono.md"
    ).read_text(encoding="utf-8")
    assert "notes-dossier" not in content
    http.close()


def test_foreign_repo_url_dossier_skipped_with_warning(tmp_path):
    profile_dir = profile(tmp_path)
    gh, http = github(
        mono_handler(
            [repo("mono")],
            {
                "README.md": "# readme",
                "stolen-dossier.md": dossier("elsewhere", "X"),
            },
        )
    )
    report = sync_github_sources(profile_dir, "me", client=gh)
    filenames = {
        doc.filename for doc in load_manifest(profile_dir).docs if doc.origin == "github"
    }
    assert filenames == {f"{GITHUB_DOC_PREFIX}mono.md"}
    assert any("stolen-dossier.md" in warning for warning in report.warnings)
    http.close()


def test_dossier_overflow_warns_and_keeps_first_five(tmp_path):
    profile_dir = profile(tmp_path)
    files = {"README.md": "# readme"}
    for letter in "abcdef":
        files[f"{letter}-dossier.md"] = dossier("mono", letter)
    gh, http = github(mono_handler([repo("mono")], files))
    report = sync_github_sources(profile_dir, "me", client=gh)
    github_docs = [doc for doc in load_manifest(profile_dir).docs if doc.origin == "github"]
    assert len(github_docs) == 5
    assert not any("f-dossier" in doc.filename for doc in github_docs)
    assert any("f-dossier.md" in warning for warning in report.warnings)
    http.close()


def test_per_repo_failure_keeps_previous_dossier_docs(tmp_path):
    profile_dir = profile(tmp_path)
    gh, http = github(
        mono_handler(
            [repo("mono")], {"api-dossier.md": dossier("mono", "API Gateway")}
        )
    )
    sync_github_sources(profile_dir, "me", client=gh)
    http.close()

    def failing(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/users/me/repos":
            return httpx.Response(200, json=[repo("mono")])
        return httpx.Response(500)

    broken, broken_http = github(failing)
    report = sync_github_sources(profile_dir, "me", client=broken)
    assert "mono" in report.failures
    assert report.removed == []
    filenames = {
        doc.filename for doc in load_manifest(profile_dir).docs if doc.origin == "github"
    }
    assert filenames == {f"{GITHUB_DOC_PREFIX}mono--api-dossier.md"}
    broken_http.close()


def test_dossier_content_written_verbatim_and_capped(tmp_path):
    profile_dir = profile(tmp_path)
    text = dossier("mono", "API Gateway") + "x" * 40_000
    gh, http = github(mono_handler([repo("mono")], {"api-dossier.md": text}))
    sync_github_sources(profile_dir, "me", client=gh)
    written = (
        profile_dir / "sources" / f"{GITHUB_DOC_PREFIX}mono--api-dossier.md"
    ).read_bytes()
    assert written.startswith(b"---\nrepo_url: https://github.com/me/mono")
    assert len(written) <= 30_000
    http.close()


def test_sanitized_dossier_stem_collisions_write_distinct_stable_docs(tmp_path):
    profile_dir = profile(tmp_path)
    gh, http = github(
        mono_handler(
            [repo("mono")],
            {
                "api dossier.md": dossier("mono", "API One"),
                "api-dossier.md": dossier("mono", "API Two"),
            },
        )
    )
    first = sync_github_sources(profile_dir, "me", client=gh)
    filenames = sorted(
        doc.filename for doc in load_manifest(profile_dir).docs if doc.origin == "github"
    )
    assert len(filenames) == 2
    assert filenames[0] != filenames[1]
    assert all(name.startswith(f"{GITHUB_DOC_PREFIX}mono--api-dossier-") for name in filenames)
    assert len(first.written) == 2
    assert sync_github_sources(profile_dir, "me", client=gh).written == []
    http.close()


def test_uploaded_dossier_supersedes_all_harvested_repo_docs(tmp_path):
    profile_dir = profile(tmp_path)
    gh, http = github(
        mono_handler(
            [repo("mono")],
            {
                "api-dossier.md": dossier("mono", "API Gateway"),
                "ui-dossier.md": dossier("mono", "UI Dashboard"),
            },
        )
    )
    sync_github_sources(profile_dir, "me", client=gh)
    assert sum(doc.origin == "github" for doc in load_manifest(profile_dir).docs) == 2

    upload = tmp_path / "mine-dossier.md"
    upload.write_text(dossier("mono", "Authoritative"), encoding="utf-8")
    add_source(profile_dir, upload)

    report = sync_github_sources(profile_dir, "me", client=gh)
    assert sorted(report.superseded) == [
        f"{GITHUB_DOC_PREFIX}mono--api-dossier.md",
        f"{GITHUB_DOC_PREFIX}mono--ui-dossier.md",
    ]
    assert not any(doc.origin == "github" for doc in load_manifest(profile_dir).docs)
    http.close()


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
