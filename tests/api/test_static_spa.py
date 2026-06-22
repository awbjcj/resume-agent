from fastapi.testclient import TestClient

from resume_agent.api.app import create_app


def test_spa_served_when_dist_exists(tmp_path, monkeypatch):
    dist = tmp_path / "web" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>app</title>", encoding="utf-8")
    monkeypatch.setattr("resume_agent.api.app.spa_dist_dir", lambda: dist)
    app = create_app(db_url="sqlite://")
    with TestClient(app) as client:
        # API still works
        assert client.get("/api/health").status_code == 200
        # Deep link falls back to index.html
        deep = client.get("/pipeline")
        assert deep.status_code == 200
        assert "<title>app</title>" in deep.text


def test_no_spa_mount_without_dist(tmp_path, monkeypatch):
    monkeypatch.setattr("resume_agent.api.app.spa_dist_dir", lambda: tmp_path / "missing")
    app = create_app(db_url="sqlite://")
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/pipeline").status_code == 404
