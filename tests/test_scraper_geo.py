from resume_agent.discovery.scraper.geo import resolve_geo_id


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _client(payload):
    class _C:
        def get(self, url, params=None, headers=None, timeout=None):
            return _Resp(payload)

    return _C()


def test_resolve_picks_first_geo_hit():
    payload = [
        {"id": "103624908", "type": "GEO", "displayName": "Detroit, Michigan, United States"},
        {
            "id": "103013972",
            "type": "GEO",
            "displayName": "48228, Detroit, Michigan, United States",
        },
    ]
    assert resolve_geo_id("Detroit, MI", client=_client(payload)) == "103624908"


def test_resolve_prefers_city_over_postal_variant():
    payload = [
        {
            "id": "103013972",
            "type": "GEO",
            "displayName": "48228, Detroit, Michigan, United States",
        },
        {"id": "103624908", "type": "GEO", "displayName": "Detroit, Michigan, United States"},
    ]
    assert resolve_geo_id("Detroit, MI", client=_client(payload)) == "103624908"


def test_resolve_returns_none_on_empty():
    assert resolve_geo_id("Greater Detroit Area", client=_client([])) is None


def test_resolve_returns_none_on_error():
    class _Boom:
        def get(self, *args, **kwargs):
            raise RuntimeError("network down")

    assert resolve_geo_id("Detroit, MI", client=_Boom()) is None


def test_resolve_caches_by_query():
    calls = {"n": 0}

    class _Counting:
        def get(self, url, params=None, headers=None, timeout=None):
            calls["n"] += 1
            return _Resp([{"id": "1", "type": "GEO", "displayName": "X"}])

    client = _Counting()
    cache: dict[str, str | None] = {}
    resolve_geo_id("Detroit, MI", client=client, cache=cache)
    resolve_geo_id("Detroit, MI", client=client, cache=cache)
    assert calls["n"] == 1
