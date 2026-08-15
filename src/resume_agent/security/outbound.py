from __future__ import annotations

import socket
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from ipaddress import ip_address
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

Resolver = Callable[[str], Iterable[str]]

_REDIRECTS = {301, 302, 303, 307, 308}
_MAX_REDIRECTS = 5
_TEXT_CONTENT_TYPES = frozenset({"application/xhtml+xml"})


@dataclass(frozen=True)
class PublicTextResponse:
    final_url: str
    text: str
    content_type: str
    redirect_chain: tuple[str, ...] = ()


def resolve_host(host: str) -> set[str]:
    return {
        str(address[0])
        for _family, _type, _proto, _canonname, address in socket.getaddrinfo(
            host, None, type=socket.SOCK_STREAM
        )
    }


def resolve_public_url(
    url: str, resolver: Resolver = resolve_host
) -> tuple[str, str, int | None]:
    """Validate a URL and return its host plus one pinned public address."""

    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port
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


def validate_public_url(url: str, resolver: Resolver = resolve_host) -> None:
    resolve_public_url(url, resolver)


def _authority(value: str, port: int | None) -> str:
    literal = f"[{value}]" if ":" in value else value
    return f"{literal}:{port}" if port is not None else literal


def fetch_public_text(
    url: str,
    *,
    client: httpx.Client | None = None,
    resolver: Resolver = resolve_host,
    max_bytes: int = 2_000_000,
    timeout: float = 20.0,
    headers: Mapping[str, str] | None = None,
) -> PublicTextResponse:
    """Fetch bounded text from a public address, revalidating every redirect.

    The connection uses the address that was validated for the current hop,
    while preserving the original host for HTTP routing and TLS SNI. This keeps
    all user-influenced HTTP fetches behind one DNS-rebinding-aware policy.
    """

    if len(url) > 2_048:
        raise ValueError("URL is too large")
    owns_client = client is None
    http = client if client is not None else httpx.Client(timeout=timeout)
    current = url.strip()
    redirect_chain = [current]
    try:
        for redirect_count in range(_MAX_REDIRECTS + 1):
            host, pinned_ip, port = resolve_public_url(current, resolver)
            parsed = urlsplit(current)
            pinned_url = urlunsplit(
                (
                    parsed.scheme,
                    _authority(pinned_ip, port),
                    parsed.path,
                    parsed.query,
                    "",
                )
            )
            request_headers = dict(headers or {})
            request_headers["Host"] = _authority(host, port)
            request = http.build_request(
                "GET",
                pinned_url,
                headers=request_headers,
                extensions={"sni_hostname": host},
            )
            response = http.send(request, stream=True, follow_redirects=False)
            try:
                if response.status_code in _REDIRECTS:
                    location = response.headers.get("location")
                    if not location or redirect_count == _MAX_REDIRECTS:
                        raise ValueError("too many URL redirects")
                    current = urljoin(current, location)
                    redirect_chain.append(current)
                    continue
                response.raise_for_status()
                content_type = (
                    response.headers.get("content-type", "").split(";", 1)[0].casefold()
                )
                if content_type and not (
                    content_type.startswith("text/")
                    or content_type in _TEXT_CONTENT_TYPES
                ):
                    raise ValueError(f"unsupported URL content type: {content_type}")
                declared_length = response.headers.get("content-length", "")
                if declared_length.isdigit() and int(declared_length) > max_bytes:
                    raise ValueError("URL response is too large")
                content = bytearray()
                for chunk in response.iter_bytes():
                    if len(content) + len(chunk) > max_bytes:
                        raise ValueError("URL response is too large")
                    content.extend(chunk)
                return PublicTextResponse(
                    final_url=current,
                    text=bytes(content).decode(
                        response.encoding or "utf-8", errors="replace"
                    ),
                    content_type=content_type,
                    redirect_chain=tuple(redirect_chain),
                )
            finally:
                response.close()
    finally:
        if owns_client:
            http.close()
    raise ValueError("too many URL redirects")
