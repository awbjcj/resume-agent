"""Location taxonomy: parse free-text into a normalized {city, region, country}."""

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


def normalize_region(raw: str | None, country_iso2: str | None) -> str | None:
    """US states -> USPS code. Non-US gets no region (foreign = city + country)."""
    if raw is None or not is_us(country_iso2):
        return None
    key = raw.strip().lower()
    if key.upper() in _USPS_CODES:
        return key.upper()
    return _US_STATE_TO_USPS.get(key)


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
    return StructuredLocation(
        city=(city.strip() if city and city.strip() else None),
        region=normalize_region(region, iso2),
        country=iso2,
        is_us=is_us(iso2),
        raw=raw,
    )
