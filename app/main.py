from __future__ import annotations

import logging
import time
from typing import Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import config
from app.agent import generate_response
from app.elevenlabs_tts import generate_speech_base64
from app import conversation as agent_conversation
from app.schemas import AgentResponse, AgentTurnRequest, DriverMessage, Severity, Status, StatusUpdate
from app.transcribe import TranscriptionError, transcribe_audio
from app.storage import get_issues, get_stats, load_conversation, save_conversation, save_issue, storage_mode, update_issue_status

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title=config.APP_NAME,
    version=config.APP_VERSION,
    description="Voice-first incident reporting for truck drivers, with LLM triage and a rule-based safety floor.",
)

app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
@app.get("/driver", include_in_schema=False)
@app.get("/dispatch", include_in_schema=False)
def home():
    return FileResponse(config.STATIC_DIR / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
@app.get("/favicon.png", include_in_schema=False)
def favicon():
    return FileResponse(config.STATIC_DIR / "favicon.png", media_type="image/png")


@app.get("/favicon.svg", include_in_schema=False)
def favicon_svg():
    return FileResponse(config.STATIC_DIR / "favicon.svg", media_type="image/svg+xml")


@app.get("/apple-touch-icon.png", include_in_schema=False)
@app.get("/apple-touch-icon-precomposed.png", include_in_schema=False)
def apple_touch_icon():
    return FileResponse(config.STATIC_DIR / "apple-touch-icon.png", media_type="image/png")


@app.post("/api/message", response_model=AgentResponse, tags=["driver"])
def handle_driver_message(message: DriverMessage):
    """Triage a driver's spoken report, log it, and return spoken guidance."""
    started = time.perf_counter()
    agent_result = generate_response(message.transcript)

    issue_id = save_issue(
        transcript=message.transcript,
        driver_id=message.driver_id or "unknown-driver",
        truck_id=message.truck_id or "unknown-truck",
        category=agent_result["category"],
        severity=agent_result["severity"],
        decision=agent_result["decision"],
        actions=agent_result["actions"],
        source=agent_result["source"],
    )

    audio_url = generate_speech_base64(agent_result["response_text"])

    return AgentResponse(
        transcript=message.transcript,
        issue_id=issue_id,
        audio_url=audio_url,
        total_ms=round((time.perf_counter() - started) * 1000),
        **agent_result,
    )


@app.post("/api/agent/turn", tags=["driver"])
def agent_turn(request: AgentTurnRequest):
    """One driver utterance in a multi-turn conversation with the voice agent.

    Omit conversation_id to start a new conversation. The agent may answer with a
    follow-up question (awaiting_answer=true) or act through its tools.
    """
    conversation = None
    if request.conversation_id:
        conversation = load_conversation(request.conversation_id)
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation expired or not found")
    if conversation is None:
        conversation = agent_conversation.new_conversation(request.driver_id, request.truck_id)

    result = agent_conversation.handle_turn(conversation, request.text)
    save_conversation(conversation)
    result["audio_url"] = generate_speech_base64(result["reply"])
    return result


@app.get("/api/conversations/{conversation_id}", tags=["dispatch"])
def get_conversation(conversation_id: str):
    """Transcript and tool calls for a conversation."""
    conversation = load_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation expired or not found")
    return {key: conversation[key] for key in ("id", "driver_id", "truck_id", "created_at", "transcript", "events", "incident_id", "incident", "escalated")}


# Vercel rejects request bodies over 4.5 MB
MAX_AUDIO_BYTES = 4 * 1024 * 1024


@app.post("/api/transcribe", tags=["driver"])
async def transcribe(audio: UploadFile = File(...)):
    """Transcribe a recorded voice clip (webm, mp4/m4a, ogg or wav) with Groq Whisper."""
    if not config.GROQ_API_KEY:
        raise HTTPException(status_code=503, detail="Speech-to-text is not configured")

    data = await audio.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty audio")
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio clip too large")

    try:
        text = transcribe_audio(data, audio.filename or "clip.webm", audio.content_type or "application/octet-stream")
    except TranscriptionError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return {"transcript": text}


@app.get("/api/issues", tags=["dispatch"])
def list_issues(
    severity: Optional[Severity] = None,
    status: Optional[Status] = None,
    limit: Optional[int] = Query(default=None, ge=1, le=500),
):
    """List logged incidents, newest first."""
    return {"issues": get_issues(severity=severity, status=status, limit=limit)}


@app.patch("/api/issues/{issue_id}", tags=["dispatch"])
def set_issue_status(issue_id: str, update: StatusUpdate):
    """Acknowledge or resolve an incident."""
    issue = update_issue_status(issue_id, update.status)
    if issue is None:
        raise HTTPException(status_code=404, detail="Issue not found")
    return issue


@app.get("/api/stats", tags=["dispatch"])
def stats():
    """Fleet-wide incident counts for the dispatch console."""
    return get_stats()


@app.post("/api/demo/seed", tags=["system"])
def seed_demo_data():
    """Load sample incidents so the dispatch console has something to show."""
    from app.seed import seed

    return {"seeded": seed()}


@app.get("/api/health", tags=["system"])
def health_check():
    return {
        "status": "ok",
        "service": config.APP_NAME,
        "version": config.APP_VERSION,
        "reasoning": {"provider": "groq", "model": config.GROQ_MODEL} if config.GROQ_API_KEY else {"provider": "rules", "model": None},
        "voice": "elevenlabs" if config.ELEVENLABS_API_KEY else "browser",
        "speech_to_text": "groq-whisper" if config.GROQ_API_KEY else "browser",
        "storage": storage_mode(),
    }
