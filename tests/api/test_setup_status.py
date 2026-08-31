"""setup/status aggregates per-area readiness and an overall complete flag."""

import io

import pytest
from fastapi.testclient import TestClient

from resume_tailor_harness.api.app import create_app


@pytest.fixture()
def make_client(tmp_path):
    def _make(env_text=""):
        env = tmp_path / ".env"
        env.write_text(env_text, encoding="utf-8")
        app = create_app(
            db_url="sqlite://",
            config_dir=tmp_path / "config",
            env_path=env,
            data_dir=tmp_path / "data",
        )
        return TestClient(app)

    return _make


def test_fresh_install_incomplete(make_client):
    with make_client() as client:
        body = client.get("/api/setup/status").json()
        assert body["complete"] is False
        assert body["secrets"]["anthropicKey"] is False
        assert body["profile"]["documentCount"] == 0
        assert body["profile"]["factsBuiltAt"] is None
        assert body["search"]["configured"] is False


def test_areas_flip_as_setup_progresses(make_client, tmp_path):
    with make_client("ANTHROPIC_API_KEY=sk-ant-test-abcd1234\n") as client:
        client.post(
            "/api/profile/documents",
            files={"file": ("resume.txt", io.BytesIO(b"exp"), "text/plain")},
            data={"docType": "resume"},
        )
        client.put("/api/config/search", json={"keywords": ["python"]})
        facts = tmp_path / "data" / "profile" / "facts.json"
        facts.parent.mkdir(parents=True, exist_ok=True)
        facts.write_text("{}", encoding="utf-8")

        body = client.get("/api/setup/status").json()
        assert body["secrets"]["anthropicKey"] is True
        assert body["profile"]["hasResume"] is True
        assert body["profile"]["factsBuiltAt"] is not None
        assert body["search"]["configured"] is True
        # no sources enabled yet -> still incomplete
        assert body["sources"]["enabledCount"] == 0
        assert body["complete"] is False


def test_broken_skill_manifest_is_reported_additively(make_client, tmp_path):
    root = tmp_path / "skills"
    manifest = tmp_path / "skills-lock.json"
    root.mkdir()
    manifest.write_text("{not-json", encoding="utf-8")

    with make_client(
        f"CAREER_SKILL_ROOT={root}\nCAREER_SKILL_MANIFEST={manifest}\n"
    ) as client:
        body = client.get("/api/setup/status").json()

    assert body["complete"] is False
    assert body["capabilities"]["careerSkills"]["available"] == 0
    assert body["capabilities"]["careerSkills"]["unavailable"] >= 1
