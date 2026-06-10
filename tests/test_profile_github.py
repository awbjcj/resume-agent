import httpx

from resume_agent.profile.github import GitHubClient


def _client(handler) -> GitHubClient:
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport, base_url="https://api.github.com")
    return GitHubClient(token="t", client=http)


def test_fetch_profile():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/users/ada"
        return httpx.Response(200, json={"login": "ada", "followers": 42, "public_repos": 3})

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
