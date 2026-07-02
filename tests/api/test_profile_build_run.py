"""Profile build launches as a run; preconditions fail fast with 400."""

import io

import pytest
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app


@pytest.fixture()
def client(tmp_path):
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=sk-ant-test-abcd1234\n", encoding="utf-8")
    app = create_app(db_url="sqlite://", config_dir=tmp_path / "config",
                     env_path=env, data_dir=tmp_path / "data")
    with TestClient(app) as c:
        yield c


def test_build_without_resume_is_400(client):
    resp = client.post("/api/profile/build")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "SETUP_INCOMPLETE"


def test_build_without_key_is_400(tmp_path):
    app = create_app(db_url="sqlite://", config_dir=tmp_path / "config",
                     env_path=tmp_path / ".env", data_dir=tmp_path / "data")
    with TestClient(app) as client:
        client.post(
            "/api/profile/documents",
            files={"file": ("resume.txt", io.BytesIO(b"experience"), "text/plain")},
            data={"docType": "resume"},
        )
        resp = client.post("/api/profile/build")
        assert resp.status_code == 400


def test_build_launches_run(client, monkeypatch):
    client.post(
        "/api/profile/documents",
        files={"file": ("resume.txt", io.BytesIO(b"experience"), "text/plain")},
        data={"docType": "resume"},
    )

    from resume_agent.services import profile_build

    def fake_run(reporter, **kwargs):
        return {"experiences": 2, "projects": 1, "warnings": []}

    monkeypatch.setattr(profile_build, "run_profile_build", fake_run)
    resp = client.post("/api/profile/build")
    assert resp.status_code == 202
    body = resp.json()
    assert body["kind"] == "profile-build"
    assert body["runId"]
