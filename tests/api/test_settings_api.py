import io
import json
import tarfile


def _login(client):
    response = client.post(
        "/api/auth/login",
        json={"identifier": "owner", "password": "owner-password"},
    )
    assert response.status_code == 200


def _bundle(sections: list[str], files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        blob = json.dumps(
            {"version": 1, "exportedAt": "", "sections": sections}
        ).encode("utf-8")
        info = tarfile.TarInfo("manifest.json")
        info.size = len(blob)
        tar.addfile(info, io.BytesIO(blob))
        for name, text in files.items():
            payload = text.encode("utf-8")
            member = tarfile.TarInfo(name)
            member.size = len(payload)
            tar.addfile(member, io.BytesIO(payload))
    return buffer.getvalue()


def test_sections_lists_every_section(mu_client):
    _login(mu_client)
    response = mu_client.get("/api/settings/sections")
    assert response.status_code == 200
    body = response.json()
    ids = [section["id"] for section in body["sections"]]
    assert len(ids) == 12
    assert "sources" in ids
    assert all("customized" in section for section in body["sections"])


def test_sections_requires_authentication(mu_client):
    assert mu_client.get("/api/settings/sections").status_code == 401


def test_export_returns_a_gzip_archive(mu_client):
    _login(mu_client)
    response = mu_client.get("/api/settings/bundle")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/gzip"


def test_preview_reports_sections_without_writing(mu_client):
    _login(mu_client)
    response = mu_client.post(
        "/api/settings/bundle/preview",
        files={
            "file": (
                "b.tar.gz",
                _bundle(["sources"], {"config/connectors.yaml": "companies: []\n"}),
                "application/gzip",
            )
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert [section["id"] for section in body["sections"]] == ["sources"]
    assert body["unknownSections"] == []


def test_import_requires_the_confirm_token(mu_client):
    _login(mu_client)
    response = mu_client.post(
        "/api/settings/bundle",
        files={"file": ("b.tar.gz", _bundle([], {}), "application/gzip")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "CONFIRM_REQUIRED"


def test_import_applies_the_bundle(mu_client):
    _login(mu_client)
    response = mu_client.post(
        "/api/settings/bundle?confirm=APPLY",
        files={
            "file": (
                "b.tar.gz",
                _bundle(
                    ["sources"], {"config/connectors.yaml": "companies:\n  urls: []\n"}
                ),
                "application/gzip",
            )
        },
    )
    assert response.status_code == 200
    assert response.json()["applied"] == ["sources"]


def test_import_rejects_a_corrupt_bundle(mu_client):
    _login(mu_client)
    response = mu_client.post(
        "/api/settings/bundle?confirm=APPLY",
        files={"file": ("b.tar.gz", b"not gzip", "application/gzip")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_BUNDLE"


def test_reset_of_an_unknown_section_is_404(mu_client):
    _login(mu_client)
    response = mu_client.post("/api/settings/sections/nope/reset")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_reset_is_refused_while_runs_are_active(mu_client, mu_app, monkeypatch):
    _login(mu_client)
    monkeypatch.setattr(
        mu_app.state.run_manager, "list_active", lambda user_id=None: ["run-1"]
    )
    response = mu_client.post("/api/settings/sections/sources/reset")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RUNS_ACTIVE"


def test_reset_returns_the_section_uncustomized(mu_client):
    _login(mu_client)
    mu_client.post(
        "/api/settings/bundle?confirm=APPLY",
        files={
            "file": (
                "b.tar.gz",
                _bundle(
                    ["sources"], {"config/connectors.yaml": "companies:\n  urls: []\n"}
                ),
                "application/gzip",
            )
        },
    )
    response = mu_client.post("/api/settings/sections/sources/reset")
    assert response.status_code == 200
    assert response.json() == {
        "id": "sources",
        "label": "Company sources",
        "customized": False,
    }
