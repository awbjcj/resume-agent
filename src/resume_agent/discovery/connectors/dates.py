import re
from datetime import datetime, timedelta, timezone

_RELATIVE_RE = re.compile(r"^\s*(\d+)\s+(minute|hour|day|week)s?\s+ago\s*$", re.I)


def parse_iso_datetime(value: object | None) -> datetime | None:
    """Parse source ISO timestamps as aware UTC datetimes."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_epoch_millis(value: object | None) -> datetime | None:
    """Parse an epoch-milliseconds timestamp (e.g. Lever ``createdAt``) as UTC."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def parse_relative_posted_at(
    value: str | None, now: datetime | None = None
) -> datetime | None:
    """Parse simple source labels like ``2 days ago`` as aware UTC datetimes."""
    if value is None:
        return None
    match = _RELATIVE_RE.match(value)
    if match is None:
        return None

    amount = int(match.group(1))
    unit = match.group(2).lower()
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    else:
        current = current.astimezone(timezone.utc)

    deltas = {
        "minute": timedelta(minutes=amount),
        "hour": timedelta(hours=amount),
        "day": timedelta(days=amount),
        "week": timedelta(weeks=amount),
    }
    return current - deltas[unit]
