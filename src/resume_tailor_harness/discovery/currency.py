"""Exchange-rate conversion for salary values extracted from job postings."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import httpx

logger = logging.getLogger(__name__)

_RATE_TTL = timedelta(hours=24)
_RATE_URL = "https://api.frankfurter.dev/v2/rates"
_rates: dict[str, tuple[float, datetime]] = {
    "USD": (1.0, datetime.max.replace(tzinfo=UTC))
}
_rates_lock = threading.Lock()


def usd_rate_for(currency: str) -> float | None:
    """Return the current USD value of one unit of ``currency``.

    Rates are cached per process for one day, so a discovery batch makes at
    most one request per source currency. Returning ``None`` on an unavailable
    or unsupported rate lets callers retain the source amount instead of
    incorrectly labelling it as USD.
    """
    source = currency.strip().upper()
    if source == "USD":
        return 1.0
    if not source.isalpha() or len(source) != 3:
        return None

    now = datetime.now(UTC)
    with _rates_lock:
        cached = _rates.get(source)
        if cached and now - cached[1] < _RATE_TTL:
            return cached[0]

    try:
        response = httpx.get(
            _RATE_URL,
            params={"base": source, "quotes": "USD"},
            timeout=5.0,
        )
        response.raise_for_status()
        payload = response.json()
        rate = payload[0].get("rate") if isinstance(payload, list) and payload else None
        if not isinstance(rate, (int, float)) or rate <= 0:
            raise ValueError("response did not contain a positive USD rate")
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        logger.warning("could not convert %s salary to USD: %s", source, exc)
        return None

    with _rates_lock:
        _rates[source] = (float(rate), now)
    return float(rate)


def convert_salary_to_usd(
    minimum: float | None,
    maximum: float | None,
    currency: str,
    *,
    rate_lookup: Callable[[str], float | None] = usd_rate_for,
) -> tuple[float | None, float | None, str]:
    """Convert salary bounds to USD, retaining source values if conversion fails."""
    source = currency.strip().upper() or "USD"
    if source == "USD" or (minimum is None and maximum is None):
        return minimum, maximum, "USD"

    rate = rate_lookup(source)
    if rate is None:
        return minimum, maximum, source

    def convert(value: float | None) -> float | None:
        return round(value * rate, 2) if value is not None else None

    return convert(minimum), convert(maximum), "USD"
