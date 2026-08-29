"""Profile build launches as a run; preconditions fail fast with 400."""

import io

import pytest
from fastapi.testclient import TestClient

from resume_agent.api.app import create_app


@pytest.fixture()
def client(tmp_path):
    env = tmp_path / ".env"
    env.write_text("ANTHROPIC_API_KEY=sk-ant-test-abcd1234\n", encoding="utf-8")
    app = create_app(
        db_url="sqlite://",
        config_dir=tmp_path / "config",
        env_path=env,
        data_dir=tmp_path / "data",
    )
    with TestClient(app) as c:
        yield c


def test_build_without_resume_is_400(client):
    resp = client.post("/api/profile/build")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "SETUP_INCOMPLETE"


def test_build_without_key_is_400(tmp_path):
    app = create_app(
        db_url="sqlite://",
        config_dir=tmp_path / "config",
        env_path=tmp_path / ".env",
        data_dir=tmp_path / "data",
    )
    with TestClient(app) as client:
        client.post(
            "/api/profile/documents",
            files={"file": ("resume.txt", io.BytesIO(b"experience"), "text/plain")},
            data={"docType": "resume"},
        )
        resp = client.post("/api/profile/build")
        assert resp.status_code == 400


def test_build_with_non_anthropic_key_launches_run(tmp_path, monkeypatch):
    """profile build uses Settings.mid_model, which may be a non-Anthropic
    provider (see llm_runner.split_provider) — any configured LLM key, not
    specifically ANTHROPIC_API_KEY, must satisfy the precondition."""
    env = tmp_path / ".env"
    env.write_text(
        "OPENAI_API_KEY=sk-oai-test-abcd1234\nMID_MODEL=openai:gpt-4.1\n",
        encoding="utf-8",
    )
    app = create_app(
        db_url="sqlite://",
        config_dir=tmp_path / "config",
        env_path=env,
        data_dir=tmp_path / "data",
    )
    with TestClient(app) as client:
        client.post(
            "/api/profile/documents",
            files={"file": ("resume.txt", io.BytesIO(b"experience"), "text/plain")},
            data={"docType": "resume"},
        )
        from resume_agent.services import profile_build

        monkeypatch.setattr(
            profile_build,
            "run_corpus_build",
            lambda reporter, **kwargs: {
                "experiences": 1,
                "projects": 0,
                "warnings": [],
            },
        )
        resp = client.post("/api/profile/build")
        assert resp.status_code == 202


def test_build_launches_run(client, monkeypatch):
    client.post(
        "/api/profile/documents",
        files={"file": ("resume.txt", io.BytesIO(b"experience"), "text/plain")},
        data={"docType": "resume"},
    )

    from resume_agent.services import profile_build

    def fake_run(reporter, **kwargs):
        return {"experiences": 2, "projects": 1, "warnings": []}

    monkeypatch.setattr(profile_build, "run_corpus_build", fake_run)
    resp = client.post("/api/profile/build")
    assert resp.status_code == 202
    body = resp.json()
    assert body["kind"] == "profile-build"
    assert body["runId"]


def test_build_registers_wizard_resume_as_primary_source(client, monkeypatch):
    client.post(
        "/api/profile/documents",
        files={"file": ("resume.txt", io.BytesIO(b"experience"), "text/plain")},
        data={"docType": "resume"},
    )
    from resume_agent.services import profile_build

    monkeypatch.setattr(
        profile_build,
        "run_corpus_build",
        lambda reporter, **kwargs: {"experiences": 0, "projects": 0, "warnings": []},
    )
    assert client.post("/api/profile/build").status_code == 202

    sources = client.get("/api/profile/sources").json()
    assert len(sources) == 1
    assert sources[0]["primary"] is True and sources[0]["mode"] == "literal"


def test_build_with_registered_sources_skips_document_store(client, monkeypatch):
    """A corpus source satisfies the precondition without any wizard document."""
    import io as _io

    client.post(
        "/api/profile/sources",
        files={"file": ("resume.txt", _io.BytesIO(b"experience"), "text/plain")},
    )
    from resume_agent.services import profile_build

    monkeypatch.setattr(
        profile_build,
        "run_corpus_build",
        lambda reporter, **kwargs: {"experiences": 0, "projects": 0, "warnings": []},
    )
    assert client.post("/api/profile/build").status_code == 202
