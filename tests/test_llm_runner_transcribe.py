"""Provider routing and availability for the audio transcription seam."""

import pytest

from resume_agent import llm_runner


def test_transcribe_rejects_provider_without_audio(monkeypatch):
    monkeypatch.setattr(llm_runner, "resolve_api_key", lambda model_id: "key")
    with pytest.raises(ValueError, match="does not support audio"):
        llm_runner.transcribe(b"audio", "audio/webm", model_id="claude-haiku-4-5-20251001")


def test_transcribe_requires_key(monkeypatch):
    monkeypatch.setattr(llm_runner, "resolve_api_key", lambda model_id: "")
    with pytest.raises(ValueError, match="no API key"):
        llm_runner.transcribe(b"audio", "audio/webm", model_id="gemini:gemini-2.5-flash")


def test_availability_follows_key_and_provider(monkeypatch):
    monkeypatch.setattr(llm_runner, "resolve_api_key", lambda model_id: "key")
    assert llm_runner.transcription_available() is True
    monkeypatch.setattr(llm_runner, "resolve_api_key", lambda model_id: "")
    assert llm_runner.transcription_available() is False
