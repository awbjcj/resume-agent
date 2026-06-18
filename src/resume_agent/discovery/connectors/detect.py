import re
from dataclasses import dataclass
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

_WORKDAY_HOST = re.compile(r"([a-z0-9-]+)\.[a-z0-9-]+\.myworkdayjobs\.com", re.IGNORECASE)


@dataclass(frozen=True)
class AtsTarget:
    ats: str
    token: str


def _first_path_segment(path: str) -> str | None:
    segments = [segment for segment in path.split("/") if segment]
    return segments[0] if segments else None


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

    workday = _WORKDAY_HOST.fullmatch(host)
    if workday:
        return AtsTarget("workday", workday.group(1))
    return None


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
    html = _get_html(url, client=client)
    if not html:
        return None

    for ats, pattern in _L2_MARKERS:
        match = pattern.search(html)
        if match:
            return AtsTarget(ats, match.group(1))

    workday = _WORKDAY_HOST.search(html)
    if workday:
        return AtsTarget("workday", workday.group(1))
    return None


def detect_ats(url: str, *, client: httpx.Client | None = None) -> AtsTarget | None:
    """Resolve a careers URL to an ATS target via URL pattern, then HTML sniff."""
    return _l1(url) or _l2(url, client=client)
