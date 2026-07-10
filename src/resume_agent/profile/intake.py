"""Quick-add notes and SSRF-safe public URL intake for profile sources."""

from __future__ import annotations

import re
import socket
import tempfile
from collections.abc import Callable, Iterable
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from resume_agent.discovery.connectors.text import html_to_text
from resume_agent.profile.corpus import SourceDoc, add_source

_SLUG = re.compile(r"[^a-z0-9]+")
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_REDIRECTS = {301, 302, 303, 307, 308}
_MAX_REDIRECTS = 5
_MAX_RESPONSE_BYTES = 1_000_000

Resolver = Callable[[str], Iterable[str]]


def _slug(value: str, fallback: str) -> str:
    return _SLUG.sub("-", value.casefold()).strip("-") or fallback


def _resolve_host(host: str) -> set[str]:
    return {
        address[0]
        for _family, _type, _proto, _canonname, address in socket.getaddrinfo(
            host, None, type=socket.SOCK_STREAM
        )
    }


def _public_url(url: str, resolver: Resolver) -> str:
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        _port = parsed.port
    except ValueError as error:
        raise ValueError("a public HTTP(S) URL is required") from error
    if (
        parsed.scheme not in {"http", "https"}
        or not host
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("a public HTTP(S) URL is required")
    try:
        addresses = {host} if ip_address(host) else set()
    except ValueError:
        try:
            addresses = set(resolver(host))
        except OSError as error:
            raise ValueError(f"could not resolve public HTTP host {host!r}") from error
    if not addresses:
        raise ValueError(f"could not resolve public HTTP host {host!r}")
    try:
        if any(not ip_address(address).is_global for address in addresses):
            raise ValueError("a public HTTP(S) URL is required")
    except ValueError as error:
        if str(error) == "a public HTTP(S) URL is required":
            raise
        raise ValueError("a public HTTP(S) URL is required") from error
    return url


def _stage_and_add(profile_dir: str | Path, filename: str, body: str) -> SourceDoc:
    with tempfile.TemporaryDirectory() as scratch:
        staged = Path(scratch) / filename
        staged.write_text(body, encoding="utf-8", newline="\n")
        return add_source(profile_dir, staged, mode="literal")


def add_note_source(profile_dir: str | Path, title: str, text: str) -> SourceDoc:
    if not text.strip():
        raise ValueError("note text is empty")
    if len(text) > 100_000:
        raise ValueError("note text is too large")
    heading = (title.strip() or "Note")[:200]
    body = f"# {heading}\n\n{text.strip()}\n"
    return _stage_and_add(profile_dir, f"note--{_slug(heading, 'note')}.md", body)


def _fetch_text(
    url: str,
    client: httpx.Client,
    resolver: Resolver,
) -> tuple[str, str]:
    current = url
    for redirect_count in range(_MAX_REDIRECTS + 1):
        _public_url(current, resolver)
        response = client.get(current, follow_redirects=False)
        if response.status_code in _REDIRECTS:
            location = response.headers.get("location")
            if not location or redirect_count == _MAX_REDIRECTS:
                raise ValueError("too many URL redirects")
            current = urljoin(current, location)
            continue
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").split(";", 1)[0].casefold()
        if content_type and not (
            content_type.startswith("text/") or content_type == "application/xhtml+xml"
        ):
            raise ValueError(f"unsupported URL content type: {content_type}")
        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise ValueError("URL response is too large")
        return current, response.text
    raise ValueError("too many URL redirects")


def add_url_source(
    profile_dir: str | Path,
    url: str,
    client: httpx.Client | None = None,
    *,
    resolver: Resolver = _resolve_host,
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
