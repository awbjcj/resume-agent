from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.api.routers import sources as sources_router


def _client():
    return TestClient(create_app(db_url="sqlite://"))


def test_list_sources_returns_views(monkeypatch):
    from resume_agent.discovery.connectors.sources import SourceView

    monkeypatch.setattr(
        sources_router,
        "list_sources",
        lambda **kwargs: [
            SourceView(
                "remoteok",
                "remoteok",
                "aggregator",
                "RemoteOK",
                True,
                True,
                "aggregator",
            )
        ],
    )

    client = _client()
    with client:
        body = client.get("/api/sources").json()

    assert body[0]["id"] == "remoteok"
    assert body[0]["displayName"] == "RemoteOK"


def test_preview_endpoint(monkeypatch):
    from resume_agent.services.sources import SourcePreview

    monkeypatch.setattr(
        sources_router,
        "preview_source",
        lambda url, label=None: SourcePreview(ok=True, url=url, kind="ashby", role_count=7),
    )

    client = _client()
    with client:
        body = client.post(
            "/api/sources/preview",
            json={"url": "https://jobs.ashbyhq.com/x"},
        ).json()

    assert body["ok"] is True
    assert body["roleCount"] == 7


def test_add_source_error_maps_to_400(monkeypatch):
    from resume_agent.services.sources import SourceError

    def boom(url, label=None, **kwargs):
        raise SourceError("nope")

    monkeypatch.setattr(sources_router, "add_source", boom)

    client = _client()
    with client:
        resp = client.post("/api/sources", json={"url": "x"})

    assert resp.status_code == 400
    assert resp.json()["error"]["message"] == "nope"


def test_patch_source_forwards_present_fields_atomically(monkeypatch):
    from resume_agent.discovery.connectors.sources import SourceView

    calls = []

    def fake_patch(source_id, **changes):
        calls.append((source_id, changes))
        return SourceView(
            id=source_id,
            kind="remoteok",
            type="aggregator",
            display_name="RemoteOK",
            enabled=changes.get("enabled", True),
            pullable=True,
            detail="aggregator",
            limit=changes.get("limit"),
        )

    monkeypatch.setattr(sources_router, "patch_source", fake_patch)
    client = _client()
    with client:
        response = client.patch(
            "/api/sources/remoteok", json={"enabled": False, "limit": 25}
        )
        cleared = client.patch("/api/sources/remoteok", json={"limit": None})

    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert response.json()["limit"] == 25
    assert cleared.json()["limit"] is None
    assert calls == [
        ("remoteok", {"enabled": False, "limit": 25}),
        ("remoteok", {"limit": None}),
    ]


def test_patch_source_rejects_empty_or_non_positive_changes():
    client = _client()
    with client:
        empty = client.patch("/api/sources/remoteok", json={})
        invalid = client.patch("/api/sources/remoteok", json={"limit": 0})

    assert empty.status_code == 400
    assert invalid.status_code == 422
