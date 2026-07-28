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


def test_every_model_default_is_a_catalogued_id():
    # `gemini-2.5-flash` was retired by the provider ("no longer available to
    # new users") and every transcription 404'd, deterministically. It was the
    # one model default pointing outside the curated catalog, so nothing
    # flagged the rot -- the tier defaults are all catalog ids. Keeping every
    # default inside the catalog is what makes the next retirement visible,
    # since MODEL_CATALOG is the list a human already maintains.
    from resume_agent.config import Settings
    from resume_agent.llm_runner import catalog_entry

    for field in ("cheap_model", "mid_model", "premium_model", "transcribe_model"):
        default = Settings.model_fields[field].default
        assert catalog_entry(default) is not None, f"{field}={default} is not catalogued"
