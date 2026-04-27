import base64
import requests
from app.config import ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID


def generate_speech_base64(text: str) -> str | None:
    if not ELEVENLABS_API_KEY:
        return None

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"

    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": ELEVENLABS_API_KEY,
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

    response = requests.post(url, headers=headers, json=payload, timeout=30)

    if response.status_code != 200:
        print("ElevenLabs error:", response.status_code, response.text)
        return None

    audio_base64 = base64.b64encode(response.content).decode("utf-8")
    return f"data:audio/mpeg;base64,{audio_base64}"