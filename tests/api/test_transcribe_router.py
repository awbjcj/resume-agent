"""Transcribe endpoint: availability, caps, and faked transcription."""

import pytest
from fastapi.testclient import TestClient

from resume_tailor_harness import llm_runner
from resume_tailor_harness.api.app import create_app


@pytest.fixture()
def client(tmp_path):
    env = tmp_path / "empty.env"
    env.write_text("", encoding="utf-8")
    with TestClient(
        create_app(
            db_url="sqlite://",
            data_dir=tmp_path / "data",
            config_dir=tmp_path / "config",
            env_path=env,
            api_token="",
        )
    ) as test_client:
        yield test_client


def test_availability_endpoint(client, monkeypatch):
    monkeypatch.setattr(llm_runner, "transcription_available", lambda: True)
    assert client.get("/api/transcribe/availability").json() == {"available": True}


def test_transcribe_returns_text(client, monkeypatch):
    monkeypatch.setattr(llm_runner, "transcription_available", lambda: True)
    monkeypatch.setattr(llm_runner, "transcribe", lambda audio, mime: "hello world")
    response = client.post(
        "/api/transcribe", files={"file": ("clip.webm", b"\x01\x02", "audio/webm")}
    )
    assert response.status_code == 200
    assert response.json() == {"text": "hello world"}


def test_transcribe_unavailable_without_key(client, monkeypatch):
    monkeypatch.setattr(llm_runner, "transcription_available", lambda: False)
    response = client.post(
        "/api/transcribe", files={"file": ("clip.webm", b"\x01", "audio/webm")}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "TRANSCRIBE_UNAVAILABLE"


def test_transcribe_rejects_bad_mime(client, monkeypatch):
    monkeypatch.setattr(llm_runner, "transcription_available", lambda: True)
    response = client.post(
        "/api/transcribe", files={"file": ("clip.txt", b"hi", "text/plain")}
    )
    assert response.status_code == 422
