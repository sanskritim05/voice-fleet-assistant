from pydantic import BaseModel
from typing import Optional, List


class DriverMessage(BaseModel):
    transcript: str
    driver_id: Optional[str] = "driver-demo-001"
    truck_id: Optional[str] = "truck-demo-8821"


class AgentResponse(BaseModel):
    transcript: str
    category: str
    severity: str
    decision: str
    response_text: str
    actions: List[str]
    issue_id: str
    audio_url: Optional[str] = None