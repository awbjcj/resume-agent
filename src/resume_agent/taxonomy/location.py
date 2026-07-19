"""Location taxonomy: parse free-text into a normalized {city, region, country}.

Two-layer design: an LLM segments free text into loose city/region/country, then
this module deterministically normalizes and, for the US, *infers* structure the
LLM (or the posting) left implicit. US postings almost never write the country —
they say "San Francisco, CA" — so region resolution runs first and feeds country
inference, rather than country gating region.
"""

import re
from dataclasses import asdict, dataclass

# Minimal controlled vocab; extend as real data demands.
_COUNTRY_TO_ISO2 = {
    "us": "US", "usa": "US", "u.s.": "US", "u.s.a.": "US",
    "united states": "US", "united states of america": "US",
    "uk": "GB", "u.k.": "GB", "united kingdom": "GB", "great britain": "GB", "england": "GB",
    "canada": "CA", "germany": "DE", "france": "FR", "india": "IN",
    "ireland": "IE", "netherlands": "NL", "australia": "AU", "singapore": "SG",
    "spain": "ES", "poland": "PL", "brazil": "BR", "japan": "JP", "israel": "IL",
}

_US_STATE_TO_USPS = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA",
    "kansas": "KS", "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV", "wisconsin": "WI",
    "wyoming": "WY", "district of columbia": "DC", "washington dc": "DC", "d.c.": "DC",
}
_USPS_CODES = set(_US_STATE_TO_USPS.values())

# AP-style / colloquial state abbreviations that are NOT themselves USPS codes.
# Two-letter forms that coincide with USPS codes (Ga., Mo., Pa., Va., Ky., …)
# resolve via `_USPS_CODES` after the trailing period is stripped, so they are
# intentionally absent here. "La." is likewise omitted: "LA" is USPS Louisiana.
_US_STATE_ABBREV = {
    "ala": "AL", "ariz": "AZ", "ark": "AR", "cal": "CA", "calif": "CA",
    "colo": "CO", "conn": "CT", "del": "DE", "fla": "FL", "ill": "IL",
    "ind": "IN", "kan": "KS", "kans": "KS", "mass": "MA", "mich": "MI",
    "minn": "MN", "miss": "MS", "mont": "MT", "neb": "NE", "nebr": "NE",
    "nev": "NV", "n mex": "NM", "n.mex": "NM", "okla": "OK", "ore": "OR",
    "oreg": "OR", "penn": "PA", "penna": "PA", "tenn": "TN", "tex": "TX",
    "wash": "WA", "wis": "WI", "wisc": "WI", "wva": "WV", "wyo": "WY",
}

# Unambiguous US metro shorthands -> (canonical_city | None, USPS region). Each
# implies the US. Deliberately excludes "LA" (USPS code for Louisiana).
_METRO_ALIASES: dict[str, tuple[str | None, str]] = {
    "nyc": ("New York", "NY"),
    "new york city": ("New York", "NY"),
    "sf": ("San Francisco", "CA"),
    "san francisco bay area": ("San Francisco", "CA"),
    "bay area": (None, "CA"),
    "silicon valley": (None, "CA"),
}

_ZIP_RE = re.compile(r"\s+\d{5}(?:-\d{4})?$")


def _key(raw: str | None) -> str:
    """Lowercase and collapse internal whitespace for dictionary lookups."""
    return " ".join(raw.lower().split()) if raw else ""


def normalize_country(raw: str | None) -> str | None:
    if raw is None:
        return None
    key = raw.strip().lower()
    if not key:
        return None
    if key.upper() in _COUNTRY_TO_ISO2.values():
        return key.upper()
    return _COUNTRY_TO_ISO2.get(key)


def is_us(country_iso2: str | None) -> bool:
    return country_iso2 == "US"


def _region_to_usps(raw: str | None) -> str | None:
    """Resolve a region candidate to a USPS code, or None.

    Tolerates "City, ST" (takes the trailing segment), a trailing ZIP,
    full state names, USPS codes, and AP-style abbreviations with a period.
    Country-agnostic: callers decide whether the result is US-applicable.
    """
    if raw is None:
        return None
    candidate = raw.strip()
    if not candidate:
        return None
    if "," in candidate:
        candidate = candidate.rsplit(",", 1)[-1]
    candidate = _ZIP_RE.sub("", candidate).strip()
    key = _key(candidate)
    for probe in (key, key.rstrip(".")):
        if probe.upper() in _USPS_CODES:
            return probe.upper()
        if probe in _US_STATE_TO_USPS:
            return _US_STATE_TO_USPS[probe]
        if probe in _US_STATE_ABBREV:
            return _US_STATE_ABBREV[probe]
    return None


def normalize_region(raw: str | None, country_iso2: str | None) -> str | None:
    """US states -> USPS code. Non-US gets no region (foreign = city + country)."""
    if not is_us(country_iso2):
        return None
    return _region_to_usps(raw)


def _split_city_region(city: str) -> tuple[str | None, str | None]:
    """Pull a trailing "…, ST" state out of a city field the LLM failed to split."""
    if "," not in city:
        return city, None
    head, tail = city.rsplit(",", 1)
    region = _region_to_usps(tail)
    if region:
        return (head.strip() or None), region
    return city, None


@dataclass
class StructuredLocation:
    city: str | None
    region: str | None
    country: str | None
    is_us: bool
    raw: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def build_location(
    city: str | None,
    region: str | None,
    country: str | None,
    raw: str | None = None,
) -> StructuredLocation:
    iso2 = normalize_country(country)
    city_value = city.strip() if city and city.strip() else None

    # Resolve a US state from the region field, then from a "City, ST" city leak.
    region_usps = _region_to_usps(region)
    if region_usps is None and city_value is not None:
        city_value, region_usps = _split_city_region(city_value)

    # Curated metro shorthands supply a region (and canonical city) and imply US.
    if city_value is not None:
        alias = _METRO_ALIASES.get(_key(city_value))
        if alias is not None:
            canonical_city, metro_region = alias
            region_usps = region_usps or metro_region
            if canonical_city is not None:
                city_value = canonical_city

    # Infer US only when the country is unresolved AND a state/metro was found.
    # A resolved non-US country (GB, CA-Canada, …) is authoritative and blocks it.
    if iso2 is None and region_usps is not None:
        iso2 = "US"

    us = is_us(iso2)
    return StructuredLocation(
        city=city_value,
        region=region_usps if us else None,
        country=iso2,
        is_us=us,
        raw=raw,
    )
