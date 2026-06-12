import re

_SENIORITY = re.compile(
    r"^(?:(?:sr\.?|senior|jr\.?|junior|lead|staff|principal|entry[- ]level)\s+)+",
    re.IGNORECASE,
)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _normalize(value: str) -> str:
    """Lowercase, replace runs of non-alphanumerics with one space, trim."""
    return _NON_ALNUM.sub(" ", value.lower()).strip()


def _normalize_title(title: str) -> str:
    return _normalize(_SENIORITY.sub("", title.strip()))


def compute_dedup_key(company: str | None, title: str | None) -> str | None:
    """A normalized ``company|title`` identity for cross-source dedupe."""
    if not company or not company.strip() or not title or not title.strip():
        return None
    return f"{_normalize(company)}|{_normalize_title(title)}"
