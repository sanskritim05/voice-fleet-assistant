"""Server-side speech-to-text with Groq Whisper.

Recording in the browser and transcribing here works the same in every browser,
unlike the Web Speech API (missing in Firefox, unreliable in Safari).
"""

from __future__ import annotations

import logging

import requests

from app import config

logger = logging.getLogger(__name__)

GROQ_TRANSCRIBE_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
STT_PROMPT = "A truck driver reporting a vehicle problem or a message for dispatch."


class TranscriptionError(Exception):
    pass


def transcribe_audio(audio: bytes, filename: str, content_type: str) -> str:
    if not config.GROQ_API_KEY:
        raise TranscriptionError("Speech-to-text is not configured")

    try:
        response = requests.post(
            GROQ_TRANSCRIBE_URL,
            headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
            files={"file": (filename, audio, content_type)},
            data={
                "model": config.GROQ_STT_MODEL,
                "language": "en",
                "response_format": "json",
                "temperature": "0",
                "prompt": STT_PROMPT,
            },
            timeout=30,
        )
        response.raise_for_status()
        return str(response.json().get("text", "")).strip()
    except requests.RequestException as error:
        detail = getattr(error.response, "text", "")[:200] if getattr(error, "response", None) is not None else ""
        logger.warning("Groq transcription failed: %s %s", error, detail)
        raise TranscriptionError("Transcription failed") from error
