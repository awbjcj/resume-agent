import html
import json
import re
from collections.abc import Iterable

from bs4 import BeautifulSoup
from markdownify import markdownify as _markdownify

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.search_config import SearchConfig
from resume_agent.taxonomy.location import join_locations as _join_locations

_MATERIAL_ICON_TOKENS = frozenset(
    {
        "business_center",
        "corporate_fare",
        "event",
        "laptop_windows",
        "location_on",
        "payments",
        "place",
        "schedule",
        "school",
        "work",
    }
)
_ESCAPED_ICON_TOKEN = re.compile(
    r"(?<!\S)\\_([a-z][a-z0-9]*(?:\\_[a-z0-9]+)*)\\_(?=\s|$|[,.])"
)
_PLAIN_ICON_TOKEN = re.compile(r"(?<!\S)_([a-z][a-z0-9]*(?:_[a-z0-9]+)*)_(?=\s|$|[,.])")
_ESCAPED_STRONG = re.compile(r"\\\*\\\*([^*\n]+?)\\\*\\\*")


def _drop_icon_token(match: re.Match[str]) -> str:
    token = match.group(1).replace("\\_", "_").lower()
    return "" if token in _MATERIAL_ICON_TOKENS else match.group(0)


def clean_job_description_text(text: str) -> str:
    """Remove source chrome tokens that leak into fetched job descriptions."""
    if not text:
        return ""
    cleaned = _ESCAPED_ICON_TOKEN.sub(_drop_icon_token, text)
    cleaned = _PLAIN_ICON_TOKEN.sub(_drop_icon_token, cleaned)
    cleaned = _ESCAPED_STRONG.sub(r"\1", cleaned)
    cleaned = re.sub(r"[ \t]+([,.;:])", r"\1", cleaned)
    lines = (re.sub(r"[ \t]{2,}", " ", line).strip() for line in cleaned.splitlines())
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def html_to_text(raw: str) -> str:
    """Unescape HTML entities then strip tags to readable text."""
    if not raw:
        return ""
    soup = BeautifulSoup(html.unescape(raw), "html.parser")
    return clean_job_description_text(soup.get_text(separator="\n", strip=True))


def html_to_markdown(raw: str) -> str:
    """Convert posting HTML to readable markdown (headings, bullets, bold preserved).

    Plain-text input passes through essentially unchanged. Used at ingest so the JD
    keeps structure for display while staying readable to the extract/fit agents.
    """
    if not raw:
        return ""
    converted = _markdownify(
        html.unescape(raw), heading_style="ATX", bullets="-"
    ).strip()
    return clean_job_description_text(converted)


def join_locations(values: Iterable[object]) -> str | None:
    """Join provider alternatives through the canonical location formatter."""
    return _join_locations(values)


def with_meta_lines(lines: list[str], jd_text: str) -> str:
    """Prepend sidebar/top-bar ``Label: value`` facts to a description body.

    Shared by the single-URL readers and the board connectors so both render
    the header identically -- the relevance gate, criteria extraction and
    tailoring all read these lines as part of the description.
    """
    kept = [line for line in lines if line]
    if not kept:
        return jd_text
    return "\n".join(kept) + ("\n\n" + jd_text if jd_text else "")


def jobposting_location(posting: dict) -> str | None:
    """Read every work location from schema.org ``JobPosting`` data."""
    locations: list[object] = []
    if posting.get("jobLocationType") == "TELECOMMUTE":
        locations.append("Remote")

    raw_locations = posting.get("jobLocation")
    candidates = raw_locations if isinstance(raw_locations, list) else [raw_locations]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        address = candidate.get("address")
        if isinstance(address, str):
            locations.append(address)
            continue
        if not isinstance(address, dict):
            continue
        parts: list[str] = []
        for key in ("addressLocality", "addressRegion", "addressCountry"):
            part = address.get(key)
            if isinstance(part, dict):
                part = part.get("name")
            if isinstance(part, str) and part.strip():
                parts.append(part.strip())
        if parts:
            locations.append(", ".join(parts))
    return join_locations(locations)


def jobposting_json_ld(raw_html: str) -> dict | None:
    """Return the first JobPosting object from JSON-LD in a public posting page."""
    soup = BeautifulSoup(raw_html, "html.parser")

    def find(node):
        if isinstance(node, list):
            return next(
                (match for item in node if (match := find(item)) is not None), None
            )
        if not isinstance(node, dict):
            return None
        types = node.get("@type")
        if isinstance(types, str) and types.casefold() == "jobposting":
            return node
        if isinstance(types, list) and any(
            str(item).casefold() == "jobposting" for item in types
        ):
            return node
        return find(node.get("@graph"))

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            if match := find(json.loads(script.string or script.get_text())):
                return match
        except (json.JSONDecodeError, TypeError):
            continue
    return None


# Word-count floor + gain a replacement JD must clear to count as "materially
# richer" than the text it would replace. Shared so the Adzuna detail-page
# enrichment and the same-source merge refresh stay in lockstep (text one side
# considers richer is the same text the other side will store).
_MIN_RICHER_WORDS = 45
_MIN_GAIN_WORDS = 15


def is_materially_richer(candidate: str, fallback: str) -> bool:
    """True if `candidate` has enough words, and enough more than `fallback`, to replace it."""
    candidate_words = len(candidate.split())
    fallback_words = len(fallback.split())
    return (
        candidate_words >= _MIN_RICHER_WORDS
        and candidate_words >= fallback_words + _MIN_GAIN_WORDS
    )


def _terms(search: SearchConfig) -> list[str]:
    return [t.strip().lower() for t in (*search.keywords, *search.titles) if t.strip()]


def primary_search_term(search: SearchConfig) -> str:
    """First non-empty title/keyword/anchor, used to shape a backend's server-side query.

    Titles precede keywords (a title is the more specific query); role_anchors are a
    last resort so configs that rely solely on anchors still send a shaped query.
    Case is preserved because some ATS search endpoints are case-sensitive.
    """
    terms = [t.strip() for t in (*search.titles, *search.keywords) if t.strip()]
    if not terms:
        terms = [t.strip() for t in search.role_anchors if t.strip()]
    return terms[0] if terms else ""


def primary_location(search: SearchConfig) -> str:
    """Return the first non-empty location for coarse server-side filtering."""
    return next(
        (location.strip() for location in search.locations if location.strip()), ""
    )


def filter_by_search(jobs: list[RawJob], search: SearchConfig) -> list[RawJob]:
    """Keep jobs whose title or JD text contains any configured term."""
    terms = _terms(search)
    if not terms:
        return jobs
    kept = []
    for job in jobs:
        haystack = f"{job.title or ''}\n{job.jd_text}".lower()
        if any(term in haystack for term in terms):
            kept.append(job)
    return kept


def _matches_any(haystack: str, terms: list[str]) -> bool:
    """True if any term appears in haystack on alphanumeric boundaries.

    Boundaries are asserted against alphanumerics rather than the regex ``\\b``
    word boundary so terms whose own edges are punctuation -- ``c++``, ``c#``,
    ``.net``, ``node.js`` -- still match instead of being silently dropped
    (``\\b`` never matches next to a non-word char like ``+``).
    """
    return any(
        re.search(
            rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])",
            haystack,
            re.IGNORECASE,
        )
        for term in terms
    )


def relevance_gate(jobs: list[RawJob], search: SearchConfig) -> list[RawJob]:
    """Title-anchored relevance gate with legacy fallback when anchors are absent."""
    anchors = [term.strip() for term in search.role_anchors if term.strip()]
    excludes = [term.strip() for term in search.exclude_terms if term.strip()]
    candidates = jobs if anchors else filter_by_search(jobs, search)

    kept: list[RawJob] = []
    for job in candidates:
        title = job.title or ""
        if excludes and title and _matches_any(title, excludes):
            continue
        if anchors:
            haystack = title or f"{job.title or ''}\n{job.jd_text}"
            if not _matches_any(haystack, anchors):
                continue
        kept.append(job)
    return kept


def title_relevance_gate(jobs: list[RawJob], search: SearchConfig) -> list[RawJob]:
    """Apply only title-safe relevance checks before a connector has JD text."""
    anchors = [term.strip() for term in search.role_anchors if term.strip()]
    excludes = [term.strip() for term in search.exclude_terms if term.strip()]

    kept: list[RawJob] = []
    for job in jobs:
        title = job.title or ""
        if excludes and title and _matches_any(title, excludes):
            continue
        if anchors and not _matches_any(title, anchors):
            continue
        kept.append(job)
    return kept
