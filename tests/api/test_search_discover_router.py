import time
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


def test_search_discover_launches_run(monkeypatch, tmp_path):
    monkeypatch.setattr(sources_router, "resolve_api_key", lambda model_id: "key")
    monkeypatch.setattr(
        sources_router,
        "run_search_discovery",
        lambda reporter, **kwargs: {
            "prompt": kwargs["prompt"],
            "suggestions": [],
        },
    )
    client = _client(tmp_path / "data")
    with client:
        launched = client.post(
            "/api/search/discover", json={"prompt": "platform roles"}
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
    assert run["result"]["prompt"] == "platform roles"


def test_search_discover_preflights_models(monkeypatch, tmp_path):
    seen = []

    def key(model_id):
        seen.append(model_id)
        return "key" if len(seen) == 1 else ""

    monkeypatch.setattr(sources_router, "resolve_api_key", key)
    client = _client(tmp_path / "data")
    with client:
        response = client.post("/api/search/discover", json={"prompt": "find roles"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "SETUP_INCOMPLETE"


def test_search_discover_rejects_short_prompt(tmp_path):
    client = _client(tmp_path / "data")
    with client:
        response = client.post("/api/search/discover", json={"prompt": "x"})
    assert response.status_code == 422
