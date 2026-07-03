"""Corpus-backed sources CRUD + anchor skeleton."""

import io

import pytest
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app
from resume_agent.models.profile import Contact, Experience, ProfileFacts, Project
from resume_agent.profile.store import save_facts


@pytest.fixture()
def client(tmp_path):
    app = create_app(db_url="sqlite://", config_dir=tmp_path / "config",
                     env_path=tmp_path / ".env", data_dir=tmp_path / "data")
    with TestClient(app) as c:
        yield c, tmp_path / "data"


def _upload(client, name="resume.txt", content=b"experience text", **fields):
    return client.post(
        "/api/profile/sources",
        files={"file": (name, io.BytesIO(content), "application/octet-stream")},
        data=fields,
    )


def test_upload_and_list_with_defaults(client):
    c, _ = client
    resp = _upload(c)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["mode"] == "literal"
    assert body["primary"] is True  # first source auto-promotes

    deck = _upload(c, name="deck.md", content=b"Cut latency 30%", mode="synthesis")
    assert deck.status_code == 201
    assert deck.json()["mode"] == "synthesis"

    listed = c.get("/api/profile/sources").json()
    assert [s["filename"] for s in listed] == ["resume.txt", "deck.md"]
    assert all("fragmentStatus" in s for s in listed)


def test_first_source_cannot_be_synthesis(client):
    c, _ = client
    resp = _upload(c, name="deck.md", mode="synthesis")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
    assert c.get("/api/profile/sources").json() == []


def test_bad_extension_and_oversize_rejected(client):
    c, _ = client
    assert _upload(c, name="malware.exe").status_code == 422
    assert _upload(c, content=b"x" * (15 * 1024 * 1024 + 1)).status_code == 422


def test_patch_mode_anchor_primary(client):
    c, _ = client
    _upload(c)
    doc_id = _upload(c, name="deck.md", content=b"Cut latency 30%", mode="synthesis").json()["id"]

    patched = c.patch(f"/api/profile/sources/{doc_id}", json={"anchor": "exp1"})
    assert patched.status_code == 200
    assert patched.json()["anchor"] == "exp1"

    cleared = c.patch(f"/api/profile/sources/{doc_id}", json={"anchor": None})
    assert cleared.json()["anchor"] is None

    literal = c.patch(f"/api/profile/sources/{doc_id}", json={"mode": "literal"})
    assert literal.json()["mode"] == "literal"

    promoted = c.patch(f"/api/profile/sources/{doc_id}", json={"primary": True})
    assert promoted.json()["primary"] is True

    assert c.patch("/api/profile/sources/nope", json={}).status_code == 404


def test_patch_synthesis_primary_rejected(client):
    c, _ = client
    _upload(c)
    doc_id = _upload(c, name="deck.md", content=b"Cut latency 30%", mode="synthesis").json()["id"]
    resp = c.patch(f"/api/profile/sources/{doc_id}", json={"primary": True})
    assert resp.status_code == 422


def test_delete_source(client):
    c, _ = client
    _upload(c)
    doc_id = _upload(c, name="notes.md").json()["id"]
    assert c.delete(f"/api/profile/sources/{doc_id}").status_code == 204
    assert c.delete(f"/api/profile/sources/{doc_id}").status_code == 404


def test_skeleton_lists_anchor_candidates(client):
    c, data_dir = client
    assert c.get("/api/profile/skeleton").json() == []

    facts = ProfileFacts(
        contact=Contact(name="Ada"),
        experience=[Experience(id="exp1", company="Acme", title="Engineer")],
        projects=[Project(id="proj1", name="Engine")],
    )
    save_facts(facts, data_dir / "profile" / "facts.json")

    rows = c.get("/api/profile/skeleton").json()
    assert {"id": "exp1", "kind": "experience", "label": "Acme — Engineer"} in rows
    assert {"id": "proj1", "kind": "project", "label": "Engine"} in rows
