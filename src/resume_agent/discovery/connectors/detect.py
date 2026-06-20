import re
from dataclasses import dataclass
from html import unescape
from urllib.parse import parse_qs, urlsplit

import httpx

_TOKEN = r"([A-Za-z0-9_-]+)"

_L1_HOSTS: list[tuple[str, str]] = [
    ("boards.greenhouse.io", "greenhouse"),
    ("job-boards.greenhouse.io", "greenhouse"),
    ("jobs.lever.co", "lever"),
    ("jobs.ashbyhq.com", "ashby"),
]

_L2_MARKERS: list[tuple[str, re.Pattern[str]]] = [
    (
        "greenhouse",
        re.compile(
            rf"(?:boards|job-boards)\.greenhouse\.io/embed/job_board\?"
            rf"[^\"'<>\s]*?for={_TOKEN}",
            re.IGNORECASE,
        ),
    ),
    (
        "greenhouse",
        re.compile(
            rf"(?:boards|job-boards)\.greenhouse\.io/(?!embed(?:/|$)){_TOKEN}"
            r"(?=$|[/?#\"'<>\s])",
            re.IGNORECASE,
        ),
    ),
    ("lever", re.compile(rf"jobs\.lever\.co/{_TOKEN}(?=$|[/?#\"'<>\s])", re.IGNORECASE)),
    ("ashby", re.compile(rf"jobs\.ashbyhq\.com/{_TOKEN}(?=$|[/?#\"'<>\s])", re.IGNORECASE)),
    (
        "ashby",
        re.compile(
            rf"__ASHBY[\s\S]{{0,500}}organizationSlug[\"']?\s*[:=]\s*[\"']{_TOKEN}[\"']",
            re.IGNORECASE,
        ),
    ),
]

_WORKDAY_HOST = re.compile(r"([a-z0-9-]+)\.([a-z0-9-]+)\.myworkdayjobs\.com", re.IGNORECASE)
_WORKDAY_URL = re.compile(
    r"(?:(?:https?:)?//)?"
    r"(?P<host>[a-z0-9-]+\.[a-z0-9-]+\.myworkdayjobs\.com)"
    r"(?P<path>/[^\"'<>\s]*)?",
    re.IGNORECASE,
)
_LOCALE_SEGMENT = re.compile(r"^[a-z]{2}(?:[-_][a-z]{2})?$", re.IGNORECASE)


@dataclass(frozen=True)
class AtsTarget:
    ats: str
    token: str = ""        # board slug for greenhouse/lever/ashby
    tenant: str = ""       # workday tenant (e.g. "generalmotors")
    datacenter: str = ""   # workday data center (e.g. "wd5")
    site: str = ""         # workday site path segment (e.g. "Careers_GM")


def _first_path_segment(path: str) -> str | None:
    segments = [segment for segment in path.split("/") if segment]
    return segments[0] if segments else None


def _workday_site_segment(path: str) -> str | None:
    segments = [segment for segment in path.split("/") if segment]
    while segments and _LOCALE_SEGMENT.fullmatch(segments[0]):
        segments.pop(0)
    if len(segments) >= 4 and segments[0].lower() == "wday" and segments[1].lower() == "cxs":
        return segments[3]
    if segments and segments[0].lower() != "wday":
        return segments[0]
    return None


def _workday_target(host: str, path: str) -> AtsTarget | None:
    workday = _WORKDAY_HOST.fullmatch(host)
    if not workday:
        return None
    site = _workday_site_segment(path)
    if not site:
        return None
    return AtsTarget(
        "workday",
        tenant=workday.group(1),
        datacenter=workday.group(2),
        site=site,
    )


_SINGLETON_HOSTS: list[tuple[str, str]] = [
    ("www.tesla.com", "tesla"),
    ("tesla.com", "tesla"),
    ("careers.google.com", "google"),
    ("www.google.com", "google"),
]


def _singleton(url: str) -> AtsTarget | None:
    """Bespoke portals identified by host alone (no token)."""
    host = (urlsplit(url).hostname or "").lower()
    path = urlsplit(url).path.lower()
    for known_host, ats in _SINGLETON_HOSTS:
        if host == known_host:
            if ats == "tesla" and not (path == "/careers" or path.startswith("/careers/")):
                continue
            if ats == "google" and host == "www.google.com" and not path.startswith("/about/careers/"):
                continue
            return AtsTarget(ats)
    return None


def _l1(url: str) -> AtsTarget | None:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    for known_host, ats in _L1_HOSTS:
        if host == known_host:
            token = _first_path_segment(parts.path)
            if ats == "greenhouse" and token == "embed":
                # Embed URLs carry the real board slug in ?for=, not the path.
                for_values = parse_qs(parts.query).get("for")
                token = for_values[0] if for_values else None
            return AtsTarget(ats, token) if token else None

    # Workday host with a usable site path -> a fetchable target; non-workday hosts and
    # workday hosts lacking a site path both yield None, so detect_ats falls to the L2 sniff.
    return _workday_target(host, parts.path)


def _get_html(url: str, *, client: httpx.Client | None = None) -> str | None:
    """Fetch raw HTML for L2 sniffing. Network errors are treated as no match."""
    try:
        getter = client.get if client is not None else httpx.get
        resp = getter(url, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        return resp.text
    except httpx.HTTPError:
        return None


def _l2(url: str, *, client: httpx.Client | None = None) -> AtsTarget | None:
    raw_html = _get_html(url, client=client)
    if not raw_html:
        return None

    for ats, pattern in _L2_MARKERS:
        match = pattern.search(raw_html)
        if match:
            return AtsTarget(ats, match.group(1))

    html = unescape(raw_html).replace("\\/", "/")
    for match in _WORKDAY_URL.finditer(html):
        target = _workday_target(match.group("host").lower(), match.group("path") or "")
        if target is not None:
            return target
    return None


def identify_host(url: str) -> AtsTarget | None:
    """Resolve a URL to its ATS by host/path alone — bespoke singleton, then URL pattern.

    Pure: no network. Callers that already hold the page (url_ingest) use this to
    avoid the L2 sniff re-fetching a page they have — and rendered — already.
    """
    return _singleton(url) or _l1(url)


def detect_ats(url: str, *, client: httpx.Client | None = None) -> AtsTarget | None:
    """Resolve a careers URL: host/path identity, then an HTML sniff for embeds."""
    return identify_host(url) or _l2(url, client=client)
