import os
from pathlib import Path

from dotenv import load_dotenv

# Load variables from .env file
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# ElevenLabs configuration
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")

# Groq LLM configuration
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_STT_MODEL = os.getenv("GROQ_STT_MODEL", "whisper-large-v3-turbo")

# App settings
APP_NAME = "Voice Fleet Assistant"
APP_VERSION = "2.0.0"
STATIC_DIR = BASE_DIR / "static"

# Running on Vercel: the deployment bundle is read-only, only /tmp is writable
ON_VERCEL = bool(os.getenv("VERCEL"))

# Upstash Redis (REST) for persistent storage on serverless hosts.
# Vercel's Upstash integration sets the KV_* names; plain Upstash uses UPSTASH_*.
REDIS_REST_URL = os.getenv("UPSTASH_REDIS_REST_URL") or os.getenv("KV_REST_API_URL")
REDIS_REST_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN") or os.getenv("KV_REST_API_TOKEN")

# File path for storing issues when Redis isn't configured (override with ISSUES_FILE, e.g. in tests)
_default_issues_file = Path("/tmp/fleetvoice/issues.json") if ON_VERCEL else BASE_DIR / "app" / "data" / "issues.json"
ISSUES_FILE = Path(os.getenv("ISSUES_FILE") or _default_issues_file)
