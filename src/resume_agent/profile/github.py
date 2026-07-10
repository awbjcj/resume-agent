import httpx
from urllib.parse import quote

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

    @staticmethod
    def _object(response: httpx.Response, label: str) -> dict:
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"GitHub {label} response must be an object")
        return payload

    @staticmethod
    def _objects(response: httpx.Response, label: str) -> list[dict]:
        payload = response.json()
        if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
            raise ValueError(f"GitHub {label} response must be a list of objects")
        return payload

    def close(self) -> None:
        self._client.close()

    def fetch_profile(self, username: str) -> dict:
        resp = self._client.get(f"/users/{username}")
        resp.raise_for_status()
        return self._object(resp, "profile")

    def fetch_repos(self, username: str) -> list[dict]:
        url: str | None = f"/users/{quote(username, safe='')}/repos"
        params: dict[str, object] | None = {"per_page": 100, "sort": "updated"}
        repos: list[dict] = []
        while url is not None:
            resp = self._client.get(url, params=params)
            resp.raise_for_status()
            repos.extend(self._objects(resp, "repositories"))
            next_link = resp.links.get("next", {}).get("url")
            url = next_link if isinstance(next_link, str) else None
            params = None
        return repos

    def fetch_readme(self, owner: str, repo: str) -> str | None:
        resp = self._client.get(
            f"/repos/{owner}/{repo}/readme",
            headers={"Accept": "application/vnd.github.raw"},
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text

    def fetch_root_listing(self, owner: str, repo: str) -> list[dict]:
        resp = self._client.get(
            f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/contents"
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        return self._objects(resp, "contents")

    def fetch_raw_file(self, owner: str, repo: str, path: str) -> str | None:
        resp = self._client.get(
            f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/contents/"
            f"{quote(path, safe='/')}",
            headers={"Accept": "application/vnd.github.raw"},
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text

    def fetch_languages(self, owner: str, repo: str) -> dict[str, int]:
        resp = self._client.get(
            f"/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/languages"
        )
        resp.raise_for_status()
        payload = self._object(resp, "languages")
        return {
            name: count
            for name, count in payload.items()
            if isinstance(name, str)
            and isinstance(count, int)
            and not isinstance(count, bool)
            and count >= 0
        }
