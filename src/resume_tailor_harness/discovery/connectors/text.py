import html
import json
import re
from collections.abc import Iterable

from bs4 import BeautifulSoup
from markdownify import markdownify as _markdownify

from resume_tailor_harness.discovery.connectors.base import RawJob
from resume_tailor_harness.discovery.search_config import SearchConfig
from resume_tailor_harness.taxonomy.location import join_locations as _join_locations

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
_ESCAPED_STRONG = re.compile(r"\\\*\\\*([^*\n]+?)\\\*\\\*")


def _is_icon_character(value: str) -> bool:
    return "a" <= value <= "z" or "0" <= value <= "9"


def _icon_token_at(text: str, start: int, *, escaped: bool) -> tuple[int, str] | None:
    """Return one source-chrome icon token without regex backtracking.

    Google/Material icons are emitted as ``_place_`` or ``\\_place\\_``. The
    former regular expressions had bounded-looking, but nested, repetitions
    that static analysis correctly treats as a potential ReDoS risk on fetched
    job descriptions. This finite scanner preserves the accepted token grammar
    while consuming each character at most once.
    """

    delimiter = "\\_" if escaped else "_"
    if not text.startswith(delimiter, start) or (
        start and not text[start - 1].isspace()
    ):
        return None
    cursor = start + len(delimiter)
    if cursor >= len(text) or not ("a" <= text[cursor] <= "z"):
        return None
    token_start = cursor
    cursor += 1
    while cursor < len(text) and _is_icon_character(text[cursor]):
        cursor += 1

    while text.startswith(delimiter, cursor):
        delimiter_start = cursor
        cursor += len(delimiter)
        if cursor == len(text) or text[cursor].isspace() or text[cursor] in ",.":
            token = text[token_start:delimiter_start].replace("\\_", "_").lower()
            return cursor, token
        if cursor >= len(text) or not _is_icon_character(text[cursor]):
            return None
        while cursor < len(text) and _is_icon_character(text[cursor]):
            cursor += 1
    return None


def _drop_material_icon_tokens(text: str, *, escaped: bool) -> str:
    kept: list[str] = []
    cursor = 0
    while cursor < len(text):
        token = _icon_token_at(text, cursor, escaped=escaped)
        if token is not None:
            end, name = token
            if name in _MATERIAL_ICON_TOKENS:
                cursor = end
                continue
        kept.append(text[cursor])
        cursor += 1
    return "".join(kept)


def _strip_horizontal_space_before_punctuation(text: str) -> str:
    """Drop spaces and tabs immediately before punctuation in linear time."""
    cleaned: list[str] = []
    for character in text:
        if character in ",.;:":
            while cleaned and cleaned[-1] in " \t":
                cleaned.pop()
        cleaned.append(character)
    return "".join(cleaned)


def clean_job_description_text(text: str) -> str:
    """Remove source chrome tokens that leak into fetched job descriptions."""
    if not text:
        return ""
    cleaned = _drop_material_icon_tokens(text, escaped=True)
    cleaned = _drop_material_icon_tokens(cleaned, escaped=False)
    cleaned = _ESCAPED_STRONG.sub(r"\1", cleaned)
    cleaned = _strip_horizontal_space_before_punctuation(cleaned)
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


_JSON_LD_EMPLOYMENT_LABELS = {
    "FULL_TIME": "Full time",
    "PART_TIME": "Part time",
    "CONTRACTOR": "Contract",
    "TEMPORARY": "Temporary",
    "INTERN": "Internship",
    "VOLUNTEER": "Volunteer",
    "PER_DIEM": "Per diem",
    "OTHER": "Other",
}
_JSON_LD_PERIODS = {
    "HOUR": "per hour",
    "DAY": "per day",
    "WEEK": "per week",
    "MONTH": "per month",
    "YEAR": "per year",
}


def _names(value) -> list[str]:
    """Flatten a schema.org field that may be a string, an object, or a list of either."""
    items = value if isinstance(value, list) else [value]
    names: list[str] = []
    for item in items:
        if isinstance(item, str) and item.strip():
            names.append(item.strip())
        elif isinstance(item, dict):
            name = item.get("name")
            if isinstance(name, str) and name.strip():
                names.append(name.strip())
    return names


def _amount(value) -> str | None:
    if isinstance(value, int | float):
        return f"{value:,.0f}"
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _json_ld_salary(posting: dict) -> str | None:
    """Render ``baseSalary`` (a MonetaryAmount) the way the page's pay band reads."""
    salary = posting.get("baseSalary") or posting.get("estimatedSalary")
    if isinstance(salary, list):
        salary = next((item for item in salary if isinstance(item, dict)), None)
    if not isinstance(salary, dict):
        return None
    value = salary.get("value")
    if not isinstance(value, dict):
        return _amount(value)
    low = _amount(value.get("minValue"))
    high = _amount(value.get("maxValue"))
    exact = _amount(value.get("value"))
    span = f"{low} - {high}" if low and high else (low or high or exact)
    if not span:
        return None
    currency = salary.get("currency") or value.get("currency")
    period = _JSON_LD_PERIODS.get(str(value.get("unitText") or "").upper())
    return " ".join(part for part in (currency, span, period) if part)


def jobposting_meta_lines(posting: dict) -> list[str]:
    """The sidebar/top-bar facts schema.org markup carries beyond the body text.

    ``description`` alone loses the pay band, employment type, and remote
    status that a posting renders in its header -- fields the fit scorer and
    tailoring rely on. Labels match ``ashby._sidebar_lines`` so a job read
    through either path produces the same text shape.
    """
    lines = []
    if location := jobposting_location(posting):
        lines.append(f"Location: {location}")

    remote = posting.get("jobLocationType") == "TELECOMMUTE"
    regions = _names(posting.get("applicantLocationRequirements"))
    if remote and regions:
        lines.append(f"Workplace Type: Remote ({', '.join(regions)})")
    elif remote:
        lines.append("Workplace Type: Remote")

    types = [
        _JSON_LD_EMPLOYMENT_LABELS.get(str(item).upper().replace("-", "_"), str(item))
        for item in _names(posting.get("employmentType"))
    ]
    if types:
        lines.append(f"Employment Type: {', '.join(types)}")

    if departments := _names(posting.get("occupationalCategory")):
        lines.append(f"Department: {', '.join(departments)}")

    if salary := _json_ld_salary(posting):
        lines.append(f"Compensation: {salary}")

    return lines


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
