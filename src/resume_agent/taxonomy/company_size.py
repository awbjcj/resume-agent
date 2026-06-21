"""Company-size taxonomy: snap free-text stage/size to three buckets."""

import re

BUCKETS = ("startup", "scaleup", "enterprise")

# Ordered substring rules; first match wins (most specific first).
_RULES: tuple[tuple[str, str], ...] = (
    ("pre-seed", "startup"),
    ("seed", "startup"),
    ("series a", "startup"),
    ("series b", "startup"),
    ("early stage", "startup"),
    ("startup", "startup"),
    ("series c", "scaleup"),
    ("series d", "scaleup"),
    ("series e", "scaleup"),
    ("growth", "scaleup"),
    ("scaleup", "scaleup"),
    ("scale-up", "scaleup"),
    ("mid-size", "scaleup"),
    ("fortune 500", "enterprise"),
    ("fortune 100", "enterprise"),
    ("publicly traded", "enterprise"),
    ("enterprise", "enterprise"),
    ("multinational", "enterprise"),
)
_COUNT = re.compile(r"(\d[\d,]*)\s*(?:-|to)\s*(\d[\d,]*)|(\d[\d,]*)\s*\+?")


def _employee_count_bucket(text: str) -> str | None:
    if "employee" not in text and "people" not in text:
        return None
    match = _COUNT.search(text)
    if match is None:
        return None
    high = match.group(2) or match.group(1) or match.group(3)
    count = int(high.replace(",", ""))
    if count <= 50:
        return "startup"
    if count <= 1000:
        return "scaleup"
    return "enterprise"


def snap(raw: str | None) -> str | None:
    """Map free-text size/stage to one of BUCKETS, or None if unrecognized."""
    if not raw:
        return None
    text = raw.strip().lower()
    if not text:
        return None
    for needle, bucket in _RULES:
        if needle in text:
            return bucket
    return _employee_count_bucket(text)
