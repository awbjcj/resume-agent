import hashlib
import re

_SENIORITY = re.compile(
    r"^(?:(?:sr\.?|senior|jr\.?|junior|lead|staff|principal|entry[- ]level)\s+)+",
    re.IGNORECASE,
)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _normalize(value: str) -> str:
    """Lowercase, replace runs of non-alphanumerics with one space, trim."""
    return _NON_ALNUM.sub(" ", value.lower()).strip()


# Conservative role-noun abbreviations expanded so cross-source title variants
# collapse to one key. Seniority words are already stripped by _SENIORITY, so
# only role nouns belong here. Keep this small to avoid over-collapsing.
_ABBREVIATIONS = {
    "swe": "software engineer",
    "sde": "software engineer",
    "eng": "engineer",
    "engr": "engineer",
    "dev": "developer",
    "mgr": "manager",
}


def _expand_abbreviations(normalized: str) -> str:
    return " ".join(_ABBREVIATIONS.get(token, token) for token in normalized.split())


def _normalize_title(title: str) -> str:
    return _expand_abbreviations(_normalize(_SENIORITY.sub("", title.strip())))


def compute_dedup_key(company: str | None, title: str | None) -> str | None:
    """A normalized ``company|title`` identity for cross-source dedupe."""
    if not company or not company.strip() or not title or not title.strip():
        return None
    return f"{_normalize(company)}|{_normalize_title(title)}"


_WHITESPACE = re.compile(r"\s+")


def compute_content_fingerprint(jd_text: str | None) -> str | None:
    """A whitespace/case-insensitive hash of a JD, used as a keyless dedup fallback."""
    if not jd_text or not jd_text.strip():
        return None
    normalized = _WHITESPACE.sub(" ", jd_text.lower()).strip()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()
