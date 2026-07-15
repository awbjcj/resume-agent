from pathlib import Path
from typing import NotRequired, TypedDict

from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.api.routers import sources as sources_router


class _AppKwargs(TypedDict):
    db_url: str
    api_token: str
    data_dir: NotRequired[Path]
    env_path: NotRequired[Path]


def _client(data_dir: Path | None = None):
    kwargs: _AppKwargs = {"db_url": "sqlite://", "api_token": ""}
    if data_dir is not None:
        data_dir.mkdir(parents=True, exist_ok=True)
        env_path = data_dir / "empty.env"
        env_path.write_text("", encoding="utf-8")
        kwargs["data_dir"] = data_dir
        kwargs["env_path"] = env_path
    return TestClient(create_app(**kwargs))


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
        lambda url, label=None, **kwargs: SourcePreview(
            ok=True, url=url or "", kind="ashby", role_count=7
        ),
    )

    client = _client()
    with client:
        body = client.post(
            "/api/sources/preview",
            json={"url": "https://jobs.ashbyhq.com/x"},
        ).json()

    assert body["ok"] is True
    assert body["roleCount"] == 7


def test_preview_endpoint_forwards_native_provider_recipe(monkeypatch):
    from resume_agent.services.sources import SourcePreview

    calls = []

    def fake_preview(**kwargs):
        calls.append(kwargs)
        return SourcePreview(
            ok=True,
            url="https://jobs.ashbyhq.com/acme",
            kind="ashby",
            token="acme",
            role_count=3,
        )

    monkeypatch.setattr(sources_router, "preview_source", fake_preview)
    client = _client()
    with client:
        response = client.post(
            "/api/sources/preview",
            json={"provider": "ashby", "token": "acme", "label": "Acme"},
        )

    assert response.status_code == 200
    assert response.json()["url"] == "https://jobs.ashbyhq.com/acme"
    assert calls[0]["provider"] == "ashby"
    assert calls[0]["token"] == "acme"
    assert calls[0]["search_path"].endswith("search.yaml")


def test_native_provider_requires_its_connection_parameters(monkeypatch):
    from resume_agent.services.sources import SourcePreview

    monkeypatch.setattr(
        sources_router,
        "preview_source",
        lambda **kwargs: SourcePreview(
            ok=False,
            url="",
            error="Company token must contain only letters, numbers, and hyphens.",
        ),
    )
    client = _client()
    with client:
        response = client.post(
            "/api/sources/preview", json={"provider": "greenhouse"}
        )

    assert response.status_code == 200
    assert response.json()["ok"] is False


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

    def fake_patch(source_id, connectors_path=None, **changes):
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


def test_discover_launches_run_with_runtime_capability(monkeypatch, tmp_path):
    import time

    monkeypatch.setattr(sources_router, "resolve_api_key", lambda model_id: "key")
    monkeypatch.setattr(
        sources_router,
        "run_source_discovery",
        lambda reporter, **kwargs: {
            "prompt": kwargs["prompt"],
            "candidates": [],
            "scrapeAvailable": kwargs["browser_enabled"],
            "scrapeUnavailableReason": None,
        },
    )
    client = _client(tmp_path / "data")
    with client:
        launched = client.post(
            "/api/sources/discover", json={"prompt": "AI infrastructure startups"}
        )
        assert launched.status_code == 202
        run_id = launched.json()["runId"]
        run = None
        for _ in range(50):
            run = client.get(f"/api/runs/{run_id}").json()
            if run["state"] in {"done", "error"}:
                break
            time.sleep(0.05)

    assert run is not None
    assert run["state"] == "done"
    assert run["result"]["prompt"] == "AI infrastructure startups"
    assert isinstance(run["result"]["scrapeAvailable"], bool)


def test_discover_preflights_both_models_and_search(monkeypatch, tmp_path):
    seen = []

    def key(model_id):
        seen.append(model_id)
        return "key" if len(seen) == 1 else ""

    monkeypatch.setattr(sources_router, "resolve_api_key", key)
    client = _client(tmp_path / "data")
    with client:
        response = client.post("/api/sources/discover", json={"prompt": "find acme"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "SETUP_INCOMPLETE"
    assert len(set(seen)) == 2


def test_discover_rejects_short_prompt(tmp_path):
    client = _client(tmp_path / "data")
    with client:
        response = client.post("/api/sources/discover", json={"prompt": "x"})
    assert response.status_code == 422
