"""LLM voice transcription: synchronous, in-memory, never persisted."""

from __future__ import annotations

from fastapi import APIRouter, UploadFile
from starlette.concurrency import run_in_threadpool

from resume_agent import llm_runner
from resume_agent.api.errors import ApiException
from resume_agent.api.schemas.base import CamelModel

router = APIRouter()

_MAX_AUDIO_BYTES = 15 * 1024 * 1024
_ALLOWED_MIME = {
    "audio/webm",
    "audio/ogg",
    "audio/mpeg",
    "audio/mp4",
    "audio/wav",
    "audio/x-wav",
}


class TranscribeAvailabilityOut(CamelModel):
    available: bool


class TranscribeOut(CamelModel):
    text: str


@router.get("/transcribe/availability", response_model=TranscribeAvailabilityOut)
def transcribe_availability():
    return TranscribeAvailabilityOut(available=llm_runner.transcription_available())


@router.post("/transcribe", response_model=TranscribeOut)
async def transcribe_audio(file: UploadFile):
    if not llm_runner.transcription_available():
        raise ApiException(
            400,
            "TRANSCRIBE_UNAVAILABLE",
            "Voice transcription needs a Gemini or OpenAI API key",
        )
    mime = (file.content_type or "").split(";")[0].strip().lower()
    if mime not in _ALLOWED_MIME:
        raise ApiException(422, "VALIDATION_ERROR", f"unsupported audio type: {mime or 'unknown'}")
    audio = await file.read()
    if not audio:
        raise ApiException(422, "VALIDATION_ERROR", "empty audio")
    if len(audio) > _MAX_AUDIO_BYTES:
        raise ApiException(422, "VALIDATION_ERROR", "audio exceeds the 15 MB limit")
    try:
        text = await run_in_threadpool(llm_runner.transcribe, audio, mime)
    except ValueError as exc:
        raise ApiException(400, "TRANSCRIBE_UNAVAILABLE", str(exc)) from exc
    except Exception as exc:
        raise ApiException(502, "TRANSCRIBE_FAILED", "Transcription failed") from exc
    return TranscribeOut(text=text)
