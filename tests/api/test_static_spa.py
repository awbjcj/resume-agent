from fastapi.testclient import TestClient

from resume_tailor_harness.api.app import create_app


def test_spa_served_when_dist_exists(tmp_path, monkeypatch):
    dist = tmp_path / "web" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><title>app</title>", encoding="utf-8"
    )
    (dist.parent / "secret.txt").write_text("secret", encoding="utf-8")
    monkeypatch.setattr("resume_tailor_harness.api.app.spa_dist_dir", lambda: dist)
    app = create_app(db_url="sqlite://")
    with TestClient(app) as client:
        # API still works
        assert client.get("/api/health").status_code == 200
        # Deep link falls back to index.html
        deep = client.get("/pipeline")
        assert deep.status_code == 200
        assert "<title>app</title>" in deep.text
        # Unknown API paths 404 with the JSON envelope, not the SPA shell.
        unknown = client.get("/api/does-not-exist")
        assert unknown.status_code == 404
        assert unknown.json()["error"]["code"] == "NOT_FOUND"
        traversal = client.get("/%2e%2e/secret.txt")
        assert traversal.status_code == 404
        assert traversal.json()["error"]["code"] == "NOT_FOUND"


def test_no_spa_mount_without_dist(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "resume_tailor_harness.api.app.spa_dist_dir", lambda: tmp_path / "missing"
    )
    app = create_app(db_url="sqlite://")
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/pipeline").status_code == 404
