"""Quick-add notes and SSRF-safe public URL intake for profile sources."""

from __future__ import annotations

import re
import socket
import tempfile
from collections.abc import Callable, Iterable
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

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
        str(address[0])
        for _family, _type, _proto, _canonname, address in socket.getaddrinfo(
            host, None, type=socket.SOCK_STREAM
        )
    }


def _resolve_public_host(url: str, resolver: Resolver) -> tuple[str, str, int | None]:
    """Validate scheme/host/credentials and pin one globally-routable address.

    DNS is resolved exactly once per hop here; the caller must connect to the
    returned ``pinned_ip`` directly (never re-resolve ``host``) or a second,
    attacker-controlled DNS answer (rebinding) can steer the real request at
    a private address after this check passed.
    """
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port  # also validates a malformed/out-of-range port
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
        literal_address = ip_address(host)
    except ValueError:
        try:
            addresses = set(resolver(host))
        except OSError as error:
            raise ValueError(f"could not resolve public HTTP host {host!r}") from error
    else:
        addresses = {str(literal_address)}
    if not addresses:
        raise ValueError(f"could not resolve public HTTP host {host!r}")
    try:
        resolved = sorted((address, ip_address(address)) for address in addresses)
    except ValueError as error:
        raise ValueError("a public HTTP(S) URL is required") from error
    if any(not parsed_ip.is_global for _address, parsed_ip in resolved):
        raise ValueError("a public HTTP(S) URL is required")
    return host, resolved[0][0], port


def _pin_authority(host: str, port: int | None) -> str:
    literal = f"[{host}]" if ":" in host else host
    return f"{literal}:{port}" if port is not None else literal


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
        host, pinned_ip, port = _resolve_public_host(current, resolver)
        parsed = urlsplit(current)
        pinned_url = urlunsplit(
            (parsed.scheme, _pin_authority(pinned_ip, port), parsed.path, parsed.query, "")
        )
        request = client.build_request(
            "GET",
            pinned_url,
            headers={"Host": _pin_authority(host, port)},
            extensions={"sni_hostname": host},
        )
        response = client.send(request, stream=True, follow_redirects=False)
        try:
            if response.status_code in _REDIRECTS:
                location = response.headers.get("location")
                if not location or redirect_count == _MAX_REDIRECTS:
                    raise ValueError("too many URL redirects")
                current = urljoin(current, location)
                continue
            response.raise_for_status()
            content_type = (
                response.headers.get("content-type", "").split(";", 1)[0].casefold()
            )
            if content_type and not (
                content_type.startswith("text/")
                or content_type == "application/xhtml+xml"
            ):
                raise ValueError(f"unsupported URL content type: {content_type}")
            declared_length = response.headers.get("content-length", "")
            if declared_length.isdigit() and int(declared_length) > _MAX_RESPONSE_BYTES:
                raise ValueError("URL response is too large")
            content = bytearray()
            for chunk in response.iter_bytes():
                if len(content) + len(chunk) > _MAX_RESPONSE_BYTES:
                    raise ValueError("URL response is too large")
                content.extend(chunk)
            return current, bytes(content).decode(
                response.encoding or "utf-8",
                errors="replace",
            )
        finally:
            response.close()
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
