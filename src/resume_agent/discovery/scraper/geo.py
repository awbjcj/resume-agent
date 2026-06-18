from typing import Any, Protocol

import httpx

_TYPEAHEAD = "https://www.linkedin.com/jobs-guest/api/typeaheadHits"
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


class _HttpLike(Protocol):
    def get(
        self,
        url: str,
        params: dict | None = ...,
        headers: dict | None = ...,
        timeout: float | None = ...,
    ) -> Any: ...


def _looks_like_postal_variant(hit: dict[str, Any]) -> bool:
    first_part = str(hit.get("displayName") or "").split(",", 1)[0].strip()
    return bool(first_part) and first_part.replace(" ", "").isdigit()


def resolve_geo_id(
    location: str,
    *,
    client: _HttpLike | None = None,
    cache: dict[str, str | None] | None = None,
) -> str | None:
    """Resolve a location string to a LinkedIn geoId via the login-free typeahead."""
    key = (location or "").strip()
    if not key:
        return None
    if cache is not None and key in cache:
        return cache[key]

    http = client or httpx
    geo_id: str | None = None
    try:
        resp = http.get(
            _TYPEAHEAD,
            params={"query": key, "typeaheadType": "GEO"},
            headers=_UA,
            timeout=20,
        )
        resp.raise_for_status()
        hits = resp.json()
        geo_hits = [
            hit
            for hit in (hits if isinstance(hits, list) else [])
            if hit.get("type") == "GEO" and hit.get("id")
        ]
        preferred = next((hit for hit in geo_hits if not _looks_like_postal_variant(hit)), None)
        chosen = preferred or (geo_hits[0] if geo_hits else None)
        if chosen:
            geo_id = str(chosen["id"])
    except Exception:
        geo_id = None

    if cache is not None:
        cache[key] = geo_id
    return geo_id
