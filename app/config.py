import os
from dotenv import load_dotenv

# Load variables from .env file
load_dotenv()

# ElevenLabs configuration
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")

# Groq LLM configuration
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# App settings
APP_NAME = "Voice Fleet Assistant"

# File path for storing issues
ISSUES_FILE = "app/data/issues.json"