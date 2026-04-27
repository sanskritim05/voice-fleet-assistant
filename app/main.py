from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.schemas import DriverMessage, AgentResponse
from app.agent import generate_response
from app.storage import save_issue, get_issues
from app.elevenlabs_tts import generate_speech_base64
from app.config import APP_NAME

app = FastAPI(title=APP_NAME)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def home():
    return FileResponse("static/index.html")


@app.post("/api/message", response_model=AgentResponse)
def handle_driver_message(message: DriverMessage):
    agent_result = generate_response(message.transcript)

    issue_id = save_issue(
        transcript=message.transcript,
        driver_id=message.driver_id or "unknown-driver",
        truck_id=message.truck_id or "unknown-truck",
        category=agent_result["category"],
        severity=agent_result["severity"],
        decision=agent_result["decision"],
        actions=agent_result["actions"],
    )

    audio_url = generate_speech_base64(agent_result["response_text"])

    return AgentResponse(
        transcript=message.transcript,
        category=agent_result["category"],
        severity=agent_result["severity"],
        decision=agent_result["decision"],
        response_text=agent_result["response_text"],
        actions=agent_result["actions"],
        issue_id=issue_id,
        audio_url=audio_url,
    )


@app.get("/api/issues")
def list_issues():
    return {"issues": get_issues()}


@app.get("/api/health")
def health_check():
    return {"status": "ok", "service": APP_NAME}