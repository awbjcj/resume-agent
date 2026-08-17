"""Location taxonomy: parse free-text into a normalized {city, region, country}.

Two-layer design: an LLM segments free text into loose city/region/country, then
this module deterministically normalizes and, for the US, *infers* structure the
LLM (or the posting) left implicit. US postings almost never write the country —
they say "San Francisco, CA" — so region resolution runs first and feeds country
inference, rather than country gating region.
"""

import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

# Minimal controlled vocab; extend as real data demands.
_COUNTRY_TO_ISO2 = {
    "us": "US", "usa": "US", "u.s.": "US", "u.s.a.": "US",
    "united states": "US", "united states of america": "US",
    "uk": "GB", "u.k.": "GB", "united kingdom": "GB", "great britain": "GB", "england": "GB",
    "canada": "CA", "germany": "DE", "france": "FR", "india": "IN",
    "ireland": "IE", "netherlands": "NL", "australia": "AU", "singapore": "SG",
    "spain": "ES", "poland": "PL", "brazil": "BR", "japan": "JP", "israel": "IL",
    "taiwan": "TW", "china": "CN", "hong kong": "HK",
    "south korea": "KR", "korea, republic of": "KR", "republic of korea": "KR",
    "mexico": "MX", "italy": "IT", "switzerland": "CH", "sweden": "SE",
    "portugal": "PT", "new zealand": "NZ", "austria": "AT", "belgium": "BE",
    "denmark": "DK", "norway": "NO", "finland": "FI",
    "czechia": "CZ", "czech republic": "CZ", "romania": "RO",
    "uae": "AE", "united arab emirates": "AE", "south africa": "ZA",
    "argentina": "AR", "colombia": "CO", "chile": "CL", "philippines": "PH",
    "vietnam": "VN", "indonesia": "ID", "malaysia": "MY", "thailand": "TH",
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
_LOCATION_SEPARATOR_RE = re.compile(r"\s*(?:\||;|//)\s*")
_REMOTE_RE = re.compile(r"\bremote\b", re.IGNORECASE)


def _key(raw: str | None) -> str:
    """Lowercase and collapse internal whitespace for dictionary lookups."""
    return " ".join(raw.lower().split()) if raw else ""


def _clean_region(raw: str | None) -> str | None:
    """Light pass-through cleanup for a non-US region: no canonical table exists.

    Strips a trailing ZIP-like suffix and collapses whitespace, but preserves
    the original casing — forcing title-case would corrupt an acronym-like
    region (e.g. a 2-letter code) if one ever shows up.
    """
    if raw is None:
        return None
    candidate = _ZIP_RE.sub("", raw.strip()).strip()
    candidate = " ".join(candidate.split())
    return candidate or None


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
    """US states -> USPS code. Other resolved countries -> cleaned pass-through."""
    if is_us(country_iso2):
        return _region_to_usps(raw)
    if country_iso2 is None:
        return None
    return _clean_region(raw)


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


def split_locations(raw: str | None) -> list[str]:
    """Split a provider location field into ordered, distinct alternatives.

    Connectors normalize multi-location fields with `` | ``, while a few
    provider payloads historically used semicolons. Accept both at this
    boundary so every downstream consumer sees the same instance model.
    """
    if not raw:
        return []
    values: list[str] = []
    seen: set[str] = set()
    for candidate in _LOCATION_SEPARATOR_RE.split(raw):
        value = " ".join(candidate.split())
        key = value.casefold()
        if not value or key in seen:
            continue
        seen.add(key)
        values.append(value)
    return values


def join_locations(values: Iterable[object]) -> str | None:
    """Render ordered location alternatives in the canonical storage format."""
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        for location in split_locations(value):
            key = location.casefold()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(location)
    return " | ".join(normalized) or None


def _parse_location(raw: str) -> StructuredLocation:
    """Best-effort deterministic parsing for one provider location instance."""
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    country: str | None = None
    region: str | None = None
    city: str | None = None

    if parts and normalize_country(parts[-1]) is not None:
        country = parts.pop()
    if _REMOTE_RE.search(raw):
        if country is None:
            trailing = re.search(r"(?:[-(]\s*)([A-Za-z.]{2,24})\)?\s*$", raw)
            if trailing and normalize_country(trailing.group(1)) is not None:
                country = trailing.group(1)
        return build_location(None, None, country, raw=raw)

    if len(parts) >= 2:
        region = parts.pop()
    city = ", ".join(parts) if parts else None
    if city is None and region is None:
        city = raw
    return build_location(city, region, country, raw=raw)


def build_locations(
    raw: str | None,
    *,
    primary: StructuredLocation | None = None,
) -> list[StructuredLocation]:
    """Build the canonical ordered location instances for a job.

    ``primary`` carries the fit agent's more informed parse for the first
    provider location. Remaining alternatives are parsed deterministically so
    a multi-location posting never collapses to one city/region/country tuple.
    """
    raw_values = split_locations(raw)
    locations: list[StructuredLocation] = []
    for index, value in enumerate(raw_values):
        if index == 0 and primary is not None:
            location = build_location(
                primary.city,
                primary.region,
                primary.country,
                raw=value,
            )
        else:
            location = _parse_location(value)
        locations.append(location)

    if not locations and primary is not None:
        locations.append(
            build_location(
                primary.city,
                primary.region,
                primary.country,
                raw=primary.raw,
            )
        )
    return locations


def location_instances_from_criteria(
    criteria: dict[str, Any] | None,
) -> list[StructuredLocation]:
    """Read canonical instances, falling back to the pre-array singular key."""
    data = criteria or {}
    raw_locations = data.get("locations")
    candidates = raw_locations if isinstance(raw_locations, list) else []
    if not candidates and isinstance(data.get("location_parts"), dict):
        candidates = [data["location_parts"]]

    locations: list[StructuredLocation] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        country = normalize_country(candidate.get("country"))
        locations.append(
            StructuredLocation(
                city=candidate.get("city"),
                region=candidate.get("region"),
                country=country,
                is_us=bool(candidate.get("is_us", country == "US")),
                raw=candidate.get("raw"),
            )
        )
    return locations


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
    if us:
        region_value = region_usps
    elif iso2 is not None:
        region_value = _clean_region(region)
    else:
        region_value = None

    return StructuredLocation(
        city=city_value,
        region=region_value,
        country=iso2,
        is_us=us,
        raw=raw,
    )


def format_free_location(raw: str) -> str:
    """Canonicalize a single free-text location tag to a regulated "City, ST" form.

    Reuses `build_location`'s city/state split and normalization (state names,
    AP abbreviations, metro aliases) rather than a second parser. `build_location`
    only splits a comma-joined "City, ST"; this adds one more fallback for the
    equally common space-joined "City ST" (the settings form's own placeholder
    text uses that shape) by trying the last whitespace token as a state. A
    value with no resolvable city or region (e.g. "Remote", a typo'd city, a
    non-US place) passes through trimmed and unchanged — this regulates
    *format*, not city spelling, and never invents a country for something
    outside the US table.
    """
    trimmed = " ".join(raw.split())
    if not trimmed:
        return trimmed
    loc = build_location(city=trimmed, region=None, country=None, raw=trimmed)
    if loc.city and loc.region:
        return f"{loc.city}, {loc.region}"
    if loc.city and " " in loc.city:
        head, _, tail = loc.city.rpartition(" ")
        region = _region_to_usps(tail)
        if head and region:
            return f"{head}, {region}"
    if loc.city:
        return loc.city
    return trimmed
