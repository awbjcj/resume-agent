"""Custom templates are validated, sandboxed, previewable, and deletable."""

import pytest
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app


VALID_TYP = b"""
#let payload = json(bytes(sys.inputs.at("data", default: "{}")))
#let zoom = float(sys.inputs.at("zoom", default: "1.0"))
#set text(size: 10pt * zoom)
= #payload.at("contact").at("name")
#payload.at("summary", default: "")
"""


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = create_app(db_url="sqlite://", config_dir=tmp_path / "config")
    with TestClient(app) as test_client:
        yield test_client


def _upload(client, name="mine.typ", body=VALID_TYP):
    return client.post(
        "/api/config/render/templates",
        files={"file": (name, body, "text/plain")},
    )


def test_list_starts_with_bundled_template(client) -> None:
    response = client.get("/api/config/render/templates")
    assert response.status_code == 200
    assert response.json()[0]["id"] == "classic"
    assert response.json()[0]["kind"] == "bundled"


def test_upload_validates_lists_and_previews(client) -> None:
    uploaded = _upload(client)
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["id"] == "custom:mine"
    assert "custom:mine" in {
        item["id"] for item in client.get("/api/config/render/templates").json()
    }
    preview = client.get("/api/config/render/templates/custom:mine/preview")
    assert preview.status_code == 200, preview.text
    assert preview.headers["content-type"] == "application/pdf"
    assert preview.content.startswith(b"%PDF")


def test_invalid_upload_preserves_existing_valid_template(client) -> None:
    assert _upload(client).status_code == 200
    invalid = _upload(client, body=b"#broken(")
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "template_invalid"
    assert (
        client.get("/api/config/render/templates/custom:mine/preview").status_code
        == 200
    )


@pytest.mark.parametrize("name", ["mine.txt", "../mine.typ", "a.b.typ"])
def test_upload_rejects_invalid_names(client, name) -> None:
    response = _upload(client, name=name)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "template_invalid"


def test_upload_rejects_files_over_200_kb(client) -> None:
    response = _upload(client, body=b"x" * (200 * 1024 + 1))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "template_invalid"


def test_preview_errors_use_standard_envelope(client) -> None:
    missing = client.get("/api/config/render/templates/custom:ghost/preview")
    assert missing.status_code == 422
    assert missing.json()["error"]["code"] == "template_not_found"


def test_delete_active_template_falls_back_to_classic(client) -> None:
    assert _upload(client).status_code == 200
    selected = client.put(
        "/api/config/render",
        json={"template": "custom:mine", "fitOnePage": True},
    )
    assert selected.status_code == 200, selected.text
    deleted = client.delete("/api/config/render/templates/mine")
    assert deleted.status_code == 204
    assert client.get("/api/config/render").json()["template"] == "classic"


@pytest.mark.parametrize("encoded_stem", ["%2E%2E", "a.b"])
def test_delete_rejects_path_like_stems(client, encoded_stem) -> None:
    response = client.delete(f"/api/config/render/templates/{encoded_stem}")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "template_not_found"
