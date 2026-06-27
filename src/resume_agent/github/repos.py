"""Verify and enrich GitHub repositories through the public API."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

import httpx

_GITHUB_PATH_PART = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class RepoMeta:
    full_name: str
    url: str
    stars: int
    description: str | None


def parse_github_url(url: str) -> tuple[str, str] | None:
    parsed = urlsplit(url.strip())
    if parsed.scheme not in {"http", "https"} or parsed.hostname != "github.com":
        return None

    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        return None
    owner, name = parts[:2]
    if name.endswith(".git"):
        name = name[:-4]
    if not _GITHUB_PATH_PART.fullmatch(owner) or not _GITHUB_PATH_PART.fullmatch(name):
        return None
    return owner, name


def verify_repo(owner: str, name: str, *, token: str = "") -> RepoMeta | None:
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = httpx.get(
        f"https://api.github.com/repos/{owner}/{name}",
        headers=headers,
        timeout=10.0,
    )
    if response.status_code == 404:
        return None
    response.raise_for_status()

    data = response.json()
    if not isinstance(data, dict):
        raise ValueError("GitHub repository response must be an object")
    full_name = data.get("full_name")
    url = data.get("html_url")
    stars = data.get("stargazers_count")
    description = data.get("description")
    if not isinstance(full_name, str) or not full_name:
        raise ValueError("GitHub repository response has no full_name")
    if not isinstance(url, str) or parse_github_url(url) is None:
        raise ValueError("GitHub repository response has an invalid html_url")
    if not isinstance(stars, int) or isinstance(stars, bool) or stars < 0:
        raise ValueError("GitHub repository response has an invalid star count")
    if description is not None and not isinstance(description, str):
        raise ValueError("GitHub repository response has an invalid description")

    return RepoMeta(full_name, url, stars, description)
