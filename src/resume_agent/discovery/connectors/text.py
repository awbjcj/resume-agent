import html
import re

from bs4 import BeautifulSoup
from markdownify import markdownify as _markdownify

from resume_agent.discovery.connectors.base import RawJob
from resume_agent.discovery.search_config import SearchConfig


def html_to_text(raw: str) -> str:
    """Unescape HTML entities then strip tags to readable text."""
    if not raw:
        return ""
    soup = BeautifulSoup(html.unescape(raw), "html.parser")
    return soup.get_text(separator="\n", strip=True)


def html_to_markdown(raw: str) -> str:
    """Convert posting HTML to readable markdown (headings, bullets, bold preserved).

    Plain-text input passes through essentially unchanged. Used at ingest so the JD
    keeps structure for display while staying readable to the extract/fit agents.
    """
    if not raw:
        return ""
    return _markdownify(html.unescape(raw), heading_style="ATX", bullets="-").strip()


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
        re.search(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", haystack, re.IGNORECASE)
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
