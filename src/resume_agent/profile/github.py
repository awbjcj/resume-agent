import httpx

from resume_agent.config import get_settings

GITHUB_API = "https://api.github.com"


class GitHubClient:
    """Thin wrapper over the GitHub REST API. Pass ``client`` to inject a test transport."""

    def __init__(self, token: str | None = None, client: httpx.Client | None = None) -> None:
        self._token = token if token is not None else get_settings().github_token
        if client is not None:
            self._client = client
        else:
            headers = {"Accept": "application/vnd.github+json"}
            if self._token:
                headers["Authorization"] = f"Bearer {self._token}"
            self._client = httpx.Client(base_url=GITHUB_API, headers=headers, timeout=20.0)

    def fetch_profile(self, username: str) -> dict:
        resp = self._client.get(f"/users/{username}")
        resp.raise_for_status()
        return resp.json()

    def fetch_repos(self, username: str) -> list[dict]:
        resp = self._client.get(
            f"/users/{username}/repos",
            params={"per_page": 100, "sort": "updated"},
        )
        resp.raise_for_status()
        return resp.json()

    def fetch_readme(self, owner: str, repo: str) -> str | None:
        resp = self._client.get(
            f"/repos/{owner}/{repo}/readme",
            headers={"Accept": "application/vnd.github.raw"},
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text
