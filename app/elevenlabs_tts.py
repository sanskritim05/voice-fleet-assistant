from __future__ import annotations

import base64
import logging

import requests

from app import config

logger = logging.getLogger(__name__)


def generate_speech_base64(text: str) -> str | None:
    """Return the spoken response as a data URL, or None so the browser can speak it instead."""
    if not config.ELEVENLABS_API_KEY:
        return None

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{config.ELEVENLABS_VOICE_ID}"

    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": config.ELEVENLABS_API_KEY,
    }

    payload = {
        "text": text,
        "model_id": "eleven_flash_v2_5",
        "voice_settings": {
            "stability": 0.45,
            "similarity_boost": 0.75,
            "style": 0.2,
            "use_speaker_boost": True,
        },
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
    except requests.RequestException as error:
        logger.warning("ElevenLabs request failed: %s", error)
        return None

    if response.status_code != 200:
        logger.warning("ElevenLabs error %s: %s", response.status_code, response.text[:200])
        return None

    audio_base64 = base64.b64encode(response.content).decode("utf-8")
    return f"data:audio/mpeg;base64,{audio_base64}"
