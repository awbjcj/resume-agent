"""Harvest GitHub root documents into deterministic project-mode sources."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from resume_agent.profile.corpus import (
    add_source,
    doc_path,
    frontmatter_repo_url,
    load_manifest,
    remove_source,
    sources_dir,
)
from resume_agent.profile.github import GitHubClient
from resume_agent.profile.github_ingest import normalize_repo_url

GITHUB_DOC_PREFIX = "github--"
_MAX_FILE_BYTES = 30_000
_MAX_DOC_BYTES = 120_000
_SAFE_REPO_NAME = re.compile(r"[^a-z0-9._-]+")
_CONTEXT_DOC_NAMES = frozenset({"claude.md", "context.md", "agent.md", "agents.md"})


@dataclass
class HarvestReport:
    repos: list[dict] = field(default_factory=list)
    languages: dict[str, dict[str, int]] = field(default_factory=dict)
    written: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    superseded: list[str] = field(default_factory=list)
    failures: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _identities(repo: dict) -> set[str]:
    return {
        value.casefold()
        for key in ("name", "full_name")
        if isinstance((value := repo.get(key)), str) and value.strip()
    }


def select_repos(
    repos: list[dict],
    *,
    allow: tuple[str, ...] = (),
    deny: tuple[str, ...] = (),
    limit: int = 20,
) -> list[dict]:
    """Force allowed repos into a newest-first bounded selection; deny wins."""
    if not 1 <= limit <= 100:
        raise ValueError("github repo limit must be between 1 and 100")
    allow_set = {value.strip().casefold() for value in allow if value.strip()}
    deny_set = {value.strip().casefold() for value in deny if value.strip()}
    forced: list[dict] = []
    regular: list[dict] = []
    for item in repos:
        identities = _identities(item)
        if not identities or identities & deny_set:
            continue
        is_forced = bool(identities & allow_set)
        if is_forced:
            forced.append(item)
        elif not item.get("fork") and not item.get("archived"):
            regular.append(item)

    def newest(item: dict) -> str:
        pushed_at = item.get("pushed_at")
        return pushed_at if isinstance(pushed_at, str) else ""

    forced.sort(key=newest, reverse=True)
    regular.sort(key=newest, reverse=True)
    selected = [*forced, *regular[: max(0, limit - len(forced))]]
    return sorted(selected, key=newest, reverse=True)


def _pick_doc_entries(listing: list[dict]) -> list[str]:
    names = [
        name
        for entry in listing
        if entry.get("type") == "file"
        and isinstance((name := entry.get("name")), str)
        and (name.casefold().startswith("readme") or name.casefold() in _CONTEXT_DOC_NAMES)
    ]
    return sorted(names, key=lambda name: (not name.casefold().startswith("readme"), name.casefold()))


def _truncate_utf8(value: str, limit: int) -> str:
    data = value.encode("utf-8")
    return value if len(data) <= limit else data[:limit].decode("utf-8", errors="ignore")


def render_virtual_doc(
    repo: dict,
    files: list[tuple[str, str]],
    languages: dict[str, int],
) -> str:
    """Render stable, bounded markdown so unchanged repos hit the fragment cache."""
    name = str(repo.get("name") or "")
    repo_url = str(repo.get("html_url") or "")
    language_names = [
        language
        for language, _count in sorted(
            languages.items(), key=lambda item: (-item[1], item[0].casefold())
        )
    ]
    topics = sorted(
        (topic for topic in (repo.get("topics") or []) if isinstance(topic, str)),
        key=str.casefold,
    )
    lines = [
        "---",
        f"repo_url: {repo_url}",
        f"repo_name: {name}",
        "---",
        f"# Repository: {name}",
        "",
        f"- URL: {repo_url}",
        f"- Description: {repo.get('description') or ''}",
        f"- Languages: {', '.join(language_names)}",
        f"- Topics: {', '.join(topics)}",
        f"- Stars: {repo.get('stargazers_count', 0)}",
        "",
    ]
    for filename, text in sorted(files, key=lambda item: item[0].casefold()):
        lines.extend(
            [
                f"## File: {filename}",
                "",
                _truncate_utf8(text, _MAX_FILE_BYTES),
                "",
            ]
        )
    return _truncate_utf8("\n".join(lines), _MAX_DOC_BYTES)


def dossier_repo_urls(profile_dir: str | Path) -> set[str]:
    urls: set[str] = set()
    for doc in load_manifest(profile_dir).docs:
        if doc.origin != "upload" or not doc.filename.casefold().endswith(".md"):
            continue
        try:
            url = normalize_repo_url(frontmatter_repo_url(doc_path(profile_dir, doc).read_bytes()))
        except OSError:
            continue
        if url:
            urls.add(url)
    return urls


def _is_rate_limited(error: httpx.HTTPStatusError) -> bool:
    return error.response.status_code == 429 or (
        error.response.status_code == 403
        and error.response.headers.get("x-ratelimit-remaining") == "0"
    )


def _rate_limit_warning() -> str:
    return "GitHub rate limit hit; cached docs were preserved. Set GITHUB_TOKEN to raise the limit."


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _filename_for(repo: dict, profile_dir: str | Path) -> str:
    name_value = repo.get("name")
    name = name_value if isinstance(name_value, str) else "repo"
    slug = _SAFE_REPO_NAME.sub("-", name.casefold()).strip("-") or "repo"
    candidate = f"{GITHUB_DOC_PREFIX}{slug}.md"
    conflict = next(
        (
            doc
            for doc in load_manifest(profile_dir).docs
            if doc.filename.casefold() == candidate.casefold() and doc.origin != "github"
        ),
        None,
    )
    if conflict is None:
        return candidate
    identity = normalize_repo_url(repo.get("html_url")) or name.casefold()
    suffix = hashlib.sha1(identity.encode("utf-8")).hexdigest()[:8]
    return f"{GITHUB_DOC_PREFIX}{slug}-{suffix}.md"


def _remove_local_superseded(
    profile_dir: str | Path,
    dossiers: set[str],
    report: HarvestReport,
) -> None:
    for doc in list(load_manifest(profile_dir).docs):
        if doc.origin != "github":
            continue
        try:
            repo_url = normalize_repo_url(frontmatter_repo_url(doc_path(profile_dir, doc).read_bytes()))
        except OSError:
            continue
        if repo_url not in dossiers:
            continue
        remove_source(profile_dir, doc.id, purge=True)
        report.superseded.append(doc.filename)
        report.removed.append(doc.filename)


def sync_github_sources(
    profile_dir: str | Path,
    username: str,
    client: GitHubClient | None = None,
    *,
    allow: tuple[str, ...] = (),
    deny: tuple[str, ...] = (),
    limit: int = 20,
) -> HarvestReport:
    """Refresh GitHub virtual docs while conservatively preserving cached state."""
    report = HarvestReport()
    dossiers = dossier_repo_urls(profile_dir)
    _remove_local_superseded(profile_dir, dossiers, report)
    owns_client = client is None
    github = client if client is not None else GitHubClient()
    try:
        try:
            report.repos = github.fetch_repos(username)
        except httpx.HTTPStatusError as error:
            report.warnings.append(
                _rate_limit_warning()
                if _is_rate_limited(error)
                else f"GitHub repository listing failed: {error}"
            )
            return report
        except (httpx.HTTPError, OSError, UnicodeError, ValueError) as error:
            report.warnings.append(f"GitHub repository listing failed: {error}")
            return report

        kept: set[str] = set()
        stopped_early = False
        selected = select_repos(report.repos, allow=allow, deny=deny, limit=limit)
        for item in selected:
            name = item.get("name") if isinstance(item.get("name"), str) else ""
            owner_value = item.get("owner")
            login = owner_value.get("login") if isinstance(owner_value, dict) else None
            owner = login if isinstance(login, str) else username
            filename = _filename_for(item, profile_dir)
            if not name or normalize_repo_url(item.get("html_url")) in dossiers:
                continue
            try:
                wanted = _pick_doc_entries(github.fetch_root_listing(owner, name))
                files: list[tuple[str, str]] = []
                for entry in wanted:
                    text = github.fetch_raw_file(owner, name, entry)
                    if text is not None:
                        files.append((entry, text))
                if not files:
                    continue
                languages = github.fetch_languages(owner, name)
            except httpx.HTTPStatusError as error:
                if _is_rate_limited(error):
                    report.warnings.append(_rate_limit_warning())
                    stopped_early = True
                    break
                report.failures[name] = str(error)
                kept.add(filename)
                continue
            except (httpx.HTTPError, OSError, UnicodeError, ValueError) as error:
                report.failures[name] = str(error)
                kept.add(filename)
                continue

            full_name = item.get("full_name")
            report.languages[
                full_name if isinstance(full_name, str) else f"{owner}/{name}"
            ] = languages
            data = render_virtual_doc(item, files, languages).encode("utf-8")
            target = sources_dir(profile_dir) / filename
            if not target.exists() or target.read_bytes() != data:
                _atomic_write(target, data)
                report.written.append(filename)
            kept.add(filename)
            manifest = load_manifest(profile_dir)
            if not any(doc.filename == filename for doc in manifest.docs):
                created = add_source(profile_dir, target, mode="project", origin="github")
                if created.origin != "github" or created.filename != filename:
                    target.unlink(missing_ok=True)
                    report.failures[name] = "virtual document duplicated an upload source"
                    kept.discard(filename)

        if not stopped_early:
            for doc in list(load_manifest(profile_dir).docs):
                if doc.origin == "github" and doc.filename not in kept:
                    remove_source(profile_dir, doc.id, purge=True)
                    report.removed.append(doc.filename)
        return report
    finally:
        if owns_client:
            github.close()
