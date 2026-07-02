"""Upload validation, manifest atomicity, list/delete, resume resolution."""

import io

import pytest
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.services.profile_documents import DocumentStore


@pytest.fixture()
def client(tmp_path):
    app = create_app(db_url="sqlite://", config_dir=tmp_path / "config",
                     env_path=tmp_path / ".env", data_dir=tmp_path / "data")
    with TestClient(app) as c:
        yield c


def _upload(client, name="resume.pdf", doc_type="resume", content=b"%PDF-1.4 fake"):
    return client.post(
        "/api/profile/documents",
        files={"file": (name, io.BytesIO(content), "application/octet-stream")},
        data={"docType": doc_type},
    )


def test_upload_and_list(client):
    resp = _upload(client)
    assert resp.status_code == 201
    body = resp.json()
    assert body["filename"] == "resume.pdf"
    assert body["docType"] == "resume"
    listed = client.get("/api/profile/documents").json()
    assert len(listed) == 1
    assert listed[0]["id"] == body["id"]


def test_reject_bad_extension(client):
    resp = _upload(client, name="malware.exe")
    assert resp.status_code == 422
    assert client.get("/api/profile/documents").json() == []  # nothing registered


def test_reject_bad_doc_type(client):
    resp = _upload(client, doc_type="mixtape")
    assert resp.status_code == 422


def test_reject_oversize(client):
    resp = _upload(client, content=b"x" * (15 * 1024 * 1024 + 1))
    assert resp.status_code == 422


def test_delete(client):
    doc_id = _upload(client).json()["id"]
    assert client.delete(f"/api/profile/documents/{doc_id}").status_code == 204
    assert client.get("/api/profile/documents").json() == []
    assert client.delete(f"/api/profile/documents/{doc_id}").status_code == 404


def test_latest_resume_path(tmp_path):
    store = DocumentStore(tmp_path / "docs")
    assert store.latest_resume_path() is None
    store.add("old.pdf", b"a", "resume")
    rec = store.add("new.pdf", b"b", "resume")
    store.add("notes.md", b"c", "other")
    path = store.latest_resume_path()
    assert path is not None and path.name == "new.pdf" and rec.id in str(path)
