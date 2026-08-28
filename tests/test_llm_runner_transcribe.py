"""Provider routing and availability for the audio transcription and speech seams."""

from types import SimpleNamespace

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


def test_speech_rejects_non_openai_provider(monkeypatch):
    monkeypatch.setattr(llm_runner, "resolve_api_key", lambda model_id: "key")
    with pytest.raises(ValueError, match="does not support speech synthesis"):
        llm_runner.synthesize_speech("hello", model_id="gemini:gemini-3.5-flash-lite")


def test_speech_requires_key(monkeypatch):
    monkeypatch.setattr(
        llm_runner,
        "get_settings",
        lambda: SimpleNamespace(
            speech_model="openai:gpt-4o-mini-tts",
            speech_voice="marin",
            openai_api_key="",
        ),
    )
    with pytest.raises(ValueError, match="no API key"):
        llm_runner.synthesize_speech("hello", model_id="openai:gpt-4o-mini-tts")


def test_speech_availability_requires_direct_openai_key(monkeypatch):
    settings = SimpleNamespace(
        speech_model="openai:gpt-4o-mini-tts",
        openai_api_key="speech-key",
    )
    monkeypatch.setattr(llm_runner, "get_settings", lambda: settings)
    assert llm_runner.speech_available() is True
    settings.openai_api_key = ""
    assert llm_runner.speech_available() is False


def test_speech_uses_direct_openai_client_and_returns_mp3(monkeypatch):
    import openai

    seen: dict[str, object] = {}

    class FakeSpeech:
        def create(self, **kwargs):
            seen["request"] = kwargs
            return SimpleNamespace(read=lambda: b"mp3-bytes")

    class FakeOpenAI:
        def __init__(self, **kwargs):
            seen["client"] = kwargs
            self.audio = SimpleNamespace(speech=FakeSpeech())

    monkeypatch.setattr(openai, "OpenAI", FakeOpenAI)
    monkeypatch.setattr(
        llm_runner,
        "get_settings",
        lambda: SimpleNamespace(
            speech_model="openai:gpt-4o-mini-tts",
            speech_voice="marin",
            openai_api_key="speech-key",
        ),
    )
    monkeypatch.setenv("OPENAI_BASE_URL", "https://gateway.test/v1")
    monkeypatch.setattr(
        "resume_agent.tenancy.limits.enforce_agent_budget", lambda _agent: None
    )

    assert llm_runner.synthesize_speech(
        "Read this exactly.",
        model_id="openai:gpt-4o-mini-tts",
        voice="marin",
    ) == b"mp3-bytes"
    assert seen["client"] == {
        "api_key": "speech-key",
        "base_url": "https://api.openai.com/v1",
    }
    assert seen["request"] == {
        "model": "gpt-4o-mini-tts",
        "voice": "marin",
        "input": "Read this exactly.",
        "instructions": "Speak as a professional interviewer. Read the supplied text exactly without adding or omitting words.",
        "response_format": "mp3",
    }


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
    assert Settings.model_fields["speech_model"].default == "openai:gpt-4o-mini-tts"
