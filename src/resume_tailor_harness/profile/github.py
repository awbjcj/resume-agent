import httpx
from urllib.parse import quote

from resume_tailor_harness.config import get_settings

GITHUB_API = "https://api.github.com"

_REPO_OPTIONAL_STRINGS = (
    "full_name",
    "html_url",
    "description",
    "language",
    "homepage",
    "pushed_at",
    "updated_at",
)
_REPO_COUNTS = ("stargazers_count", "forks_count")


def _optional_string(payload: dict, field: str, label: str) -> None:
    value = payload.get(field)
    if field in payload and value is not None and not isinstance(value, str):
        raise ValueError(f"GitHub {label} field {field!r} must be a string or null")


def _nonnegative_int(payload: dict, field: str, label: str) -> None:
    value = payload.get(field)
    if field in payload and (
        not isinstance(value, int) or isinstance(value, bool) or value < 0
    ):
        raise ValueError(
            f"GitHub {label} field {field!r} must be a non-negative integer"
        )


def _validated_profile(payload: dict) -> dict:
    if not isinstance(payload.get("login"), str) or not payload["login"]:
        raise ValueError("GitHub profile field 'login' must be a non-empty string")
    for field in ("bio", "created_at"):
        _optional_string(payload, field, "profile")
    for field in ("followers", "public_repos"):
        _nonnegative_int(payload, field, "profile")
    return payload


def _validated_repo(payload: dict) -> dict:
    if not isinstance(payload.get("name"), str) or not payload["name"]:
        raise ValueError("GitHub repository field 'name' must be a non-empty string")
    for field in _REPO_OPTIONAL_STRINGS:
        _optional_string(payload, field, "repository")
    for field in _REPO_COUNTS:
        _nonnegative_int(payload, field, "repository")
    for field in ("fork", "archived"):
        if field in payload and not isinstance(payload[field], bool):
            raise ValueError(f"GitHub repository field {field!r} must be a boolean")
    if "topics" in payload and (
        not isinstance(payload["topics"], list)
        or not all(isinstance(topic, str) for topic in payload["topics"])
    ):
        raise ValueError("GitHub repository field 'topics' must be a list of strings")
    owner = payload.get("owner")
    if owner is not None and (
        not isinstance(owner, dict) or not isinstance(owner.get("login"), str)
    ):
        raise ValueError("GitHub repository field 'owner.login' must be a string")
    return payload


class GitHubClient:
    """Thin wrapper over the GitHub REST API. Pass ``client`` to inject a test transport."""

    def __init__(
        self, token: str | None = None, client: httpx.Client | None = None
    ) -> None:
        self._token = token if token is not None else get_settings().github_token
        if client is not None:
            self._client = client
        else:
            headers = {"Accept": "application/vnd.github+json"}
            if self._token:
                headers["Authorization"] = f"Bearer {self._token}"
            self._client = httpx.Client(
                base_url=GITHUB_API, headers=headers, timeout=20.0
            )
        self._login: str | None = None
        self._login_resolved = False

    @staticmethod
    def _object(response: httpx.Response, label: str) -> dict:
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"GitHub {label} response must be an object")
        return payload

    @staticmethod
    def _objects(response: httpx.Response, label: str) -> list[dict]:
        payload = response.json()
        if not isinstance(payload, list) or not all(
            isinstance(item, dict) for item in payload
        ):
            raise ValueError(f"GitHub {label} response must be a list of objects")
        return payload

    def close(self) -> None:
        self._client.close()

    def fetch_profile(self, username: str) -> dict:
        resp = self._client.get(f"/users/{username}")
        resp.raise_for_status()
        return _validated_profile(self._object(resp, "profile"))

    def _authenticated_login(self) -> str | None:
        """Return the token owner's login, or None when it can't be confirmed."""
        if not self._login_resolved:
            self._login_resolved = True
            resp = self._client.get("/user")
            if resp.status_code == 200:
                payload = resp.json()
                login = payload.get("login") if isinstance(payload, dict) else None
                self._login = login if isinstance(login, str) and login else None
        return self._login

    def fetch_repos(self, username: str) -> list[dict]:
        # /users/{username}/repos is public-only; a repo the token owns but keeps
        # private is visible only through the authenticated-user endpoint. Use it
        # only once the token's login is confirmed to match the requested user.
        login = self._authenticated_login() if self._token else None
        if login is not None and login.casefold() == username.casefold():
            url: str | None = "/user/repos"
            params: dict[str, int | str] | None = {
                "per_page": 100,
                "sort": "updated",
                "affiliation": "owner",
            }
        else:
            url = f"/users/{quote(username, safe='')}/repos"
            params = {"per_page": 100, "sort": "updated"}
        repos: list[dict] = []
        while url is not None:
            resp = self._client.get(url, params=params)
            resp.raise_for_status()
            repos.extend(
                _validated_repo(repo) for repo in self._objects(resp, "repositories")
            )
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
