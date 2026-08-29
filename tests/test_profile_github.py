import httpx
import pytest

from resume_agent.profile.github import GitHubClient


def _client(handler) -> GitHubClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="https://api.github.com")
    return GitHubClient(token="", client=http)


def _auth_client(handler) -> GitHubClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="https://api.github.com")
    return GitHubClient(token="t", client=http)


def test_fetch_profile():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/users/ada"
        return httpx.Response(
            200, json={"login": "ada", "followers": 42, "public_repos": 3}
        )

    gh = _client(handler)
    profile = gh.fetch_profile("ada")
    assert profile["login"] == "ada"
    assert profile["followers"] == 42


def test_fetch_repos():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/users/ada/repos"
        return httpx.Response(200, json=[{"name": "engine", "stargazers_count": 10}])

    gh = _client(handler)
    repos = gh.fetch_repos("ada")
    assert repos[0]["name"] == "engine"


def test_fetch_repos_authenticated_owner_uses_user_repos_for_private():
    """The token's own private repos are only visible via /user/repos."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/user":
            return httpx.Response(200, json={"login": "ada"})
        if request.url.path == "/user/repos":
            assert request.url.params.get("affiliation") == "owner"
            return httpx.Response(200, json=[{"name": "secret", "fork": False}])
        return httpx.Response(404)

    repos = _auth_client(handler).fetch_repos("ada")
    assert [repo["name"] for repo in repos] == ["secret"]
    assert "/user/repos" in seen
    assert "/users/ada/repos" not in seen


def test_fetch_repos_authenticated_other_user_uses_public_endpoint():
    """A token whose login differs from the target only sees that user's public repos."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/user":
            return httpx.Response(200, json={"login": "bob"})
        if request.url.path == "/users/ada/repos":
            return httpx.Response(200, json=[{"name": "pub"}])
        return httpx.Response(404)

    assert [repo["name"] for repo in _auth_client(handler).fetch_repos("ada")] == [
        "pub"
    ]


def test_fetch_repos_authenticated_identity_unknown_falls_back_to_public():
    """A failed /user probe means identity is unconfirmed → public endpoint."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/user":
            return httpx.Response(403, json={"message": "bad token"})
        if request.url.path == "/users/ada/repos":
            return httpx.Response(200, json=[{"name": "pub"}])
        return httpx.Response(404)

    assert [repo["name"] for repo in _auth_client(handler).fetch_repos("ada")] == [
        "pub"
    ]


def test_fetch_repos_follows_pagination_link():
    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page")
        if page == "2":
            return httpx.Response(200, json=[{"name": "second"}])
        return httpx.Response(
            200,
            headers={
                "link": '<https://api.github.com/users/ada/repos?per_page=100&page=2>; rel="next"'
            },
            json=[{"name": "first"}],
        )

    assert [repo["name"] for repo in _client(handler).fetch_repos("ada")] == [
        "first",
        "second",
    ]


def test_fetch_repos_rejects_malformed_payload():
    gh = _client(lambda _request: httpx.Response(200, json={"name": "not-a-list"}))
    with pytest.raises(ValueError, match="repositories"):
        gh.fetch_repos("ada")


@pytest.mark.parametrize(
    "repo",
    [
        {"name": 42},
        {"name": "repo", "fork": "false"},
        {"name": "repo", "topics": ["python", 7]},
        {"name": "repo", "stargazers_count": True},
        {"name": "repo", "owner": {"login": 99}},
    ],
)
def test_fetch_repos_rejects_malformed_consumed_fields(repo):
    gh = _client(lambda _request: httpx.Response(200, json=[repo]))
    with pytest.raises(ValueError, match="repository"):
        gh.fetch_repos("ada")


def test_fetch_profile_rejects_malformed_consumed_fields():
    gh = _client(
        lambda _request: httpx.Response(
            200,
            json={"login": "ada", "followers": "many", "public_repos": 3},
        )
    )
    with pytest.raises(ValueError, match="profile"):
        gh.fetch_profile("ada")


def test_fetch_readme_returns_text():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/ada/engine/readme"
        return httpx.Response(200, text="# Engine\nThe first computer.")

    gh = _client(handler)
    readme = gh.fetch_readme("ada", "engine")
    assert readme is not None
    assert "first computer" in readme.lower()


def test_fetch_readme_missing_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    gh = _client(handler)
    assert gh.fetch_readme("ada", "engine") is None


def test_fetch_root_listing_raw_file_and_languages_validate_boundaries():
    def handler(request: httpx.Request) -> httpx.Response:
        raw_path = request.url.raw_path.decode().split("?", 1)[0]
        if raw_path == "/repos/ada/my%20repo/contents":
            return httpx.Response(
                200, json=[{"name": "README file.md", "type": "file"}]
            )
        if raw_path == "/repos/ada/my%20repo/contents/README%20file.md":
            assert request.headers["Accept"] == "application/vnd.github.raw"
            return httpx.Response(200, text="# Readme")
        if raw_path == "/repos/ada/my%20repo/languages":
            return httpx.Response(200, json={"Python": 900, "junk": "bad"})
        return httpx.Response(404)

    gh = _client(handler)
    assert gh.fetch_root_listing("ada", "my repo") == [
        {"name": "README file.md", "type": "file"}
    ]
    assert gh.fetch_raw_file("ada", "my repo", "README file.md") == "# Readme"
    assert gh.fetch_languages("ada", "my repo") == {"Python": 900}


def test_fetch_root_listing_rejects_non_object_entries():
    gh = _client(lambda _request: httpx.Response(200, json=["not-an-object"]))
    with pytest.raises(ValueError, match="contents"):
        gh.fetch_root_listing("ada", "repo")
