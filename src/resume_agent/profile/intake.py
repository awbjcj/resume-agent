"""Quick-add notes and SSRF-safe public URL intake for profile sources."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from resume_agent.discovery.connectors.text import html_to_text
from resume_agent.profile.corpus import SourceDoc, SourceMode, add_source
from resume_agent.security.paths import confined_path
from resume_agent.security.outbound import Resolver, fetch_public_text, resolve_host

_SLUG = re.compile(r"[^a-z0-9]+")
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_MAX_RESPONSE_BYTES = 1_000_000


def _slug(value: str, fallback: str) -> str:
    return _SLUG.sub("-", value.casefold()).strip("-") or fallback


def _stage_and_add(
    profile_dir: str | Path,
    filename: str,
    body: str,
    *,
    mode: SourceMode = "literal",
    anchor: str | None = None,
) -> SourceDoc:
    with tempfile.TemporaryDirectory() as scratch:
        staged = confined_path(scratch, filename)
        staged.write_text(body, encoding="utf-8", newline="\n")
        return add_source(profile_dir, staged, mode=mode, anchor=anchor)


def add_note_source(
    profile_dir: str | Path,
    title: str,
    text: str,
    *,
    anchor: str | None = None,
) -> SourceDoc:
    if not text.strip():
        raise ValueError("note text is empty")
    if len(text) > 100_000:
        raise ValueError("note text is too large")
    heading = (title.strip() or "Note")[:200]
    body = f"# {heading}\n\n{text.strip()}\n"
    target = anchor.strip() if anchor else None
    return _stage_and_add(
        profile_dir,
        f"note--{_slug(heading, 'note')}.md",
        body,
        mode="synthesis" if target else "literal",
        anchor=target,
    )


def _fetch_text(
    url: str,
    client: httpx.Client,
    resolver: Resolver,
) -> tuple[str, str]:
    response = fetch_public_text(
        url,
        client=client,
        resolver=resolver,
        max_bytes=_MAX_RESPONSE_BYTES,
        timeout=30.0,
    )
    return response.final_url, response.text


def add_url_source(
    profile_dir: str | Path,
    url: str,
    client: httpx.Client | None = None,
    *,
    resolver: Resolver = resolve_host,
) -> SourceDoc:
    if len(url) > 2_048:
        raise ValueError("URL is too large")
    owns_client = client is None
    http = client if client is not None else httpx.Client(timeout=30.0)
    try:
        final_url, raw = _fetch_text(url.strip(), http, resolver)
    finally:
        if owns_client:
            http.close()
    text = html_to_text(raw)
    if not text.strip():
        raise ValueError(f"no readable text at {final_url}")
    match = _TITLE.search(raw)
    title = html_to_text(match.group(1)).strip() if match else ""
    body = f"# {title or final_url}\n\nSource: {final_url}\n\n{text.strip()}\n"
    slug_source = title or urlsplit(final_url).hostname or "page"
    return _stage_and_add(
        profile_dir,
        f"url--{_slug(slug_source, 'page')}.md",
        body,
    )
