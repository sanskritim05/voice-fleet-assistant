from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

Severity = Literal["critical", "warning", "low"]
Status = Literal["open", "acknowledged", "resolved"]


class DriverMessage(BaseModel):
    transcript: str = Field(min_length=1, max_length=1000)
    driver_id: Optional[str] = Field(default="driver-demo-001", max_length=64)
    truck_id: Optional[str] = Field(default="truck-demo-8821", max_length=64)

    @field_validator("transcript")
    @classmethod
    def strip_transcript(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("transcript must not be blank")
        return value


class AgentResponse(BaseModel):
    transcript: str
    category: str
    severity: Severity
    decision: str
    response_text: str
    actions: List[str]
    issue_id: str
    audio_url: Optional[str] = None
    source: Literal["llm", "rules"]
    model: Optional[str] = None
    guardrail_applied: bool = False
    reasoning_ms: int = 0
    total_ms: int = 0


class StatusUpdate(BaseModel):
    status: Status


class AgentTurnRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    conversation_id: Optional[str] = Field(default=None, max_length=32)
    driver_id: str = Field(default="driver-demo-001", max_length=64)
    truck_id: str = Field(default="truck-8821", max_length=64)

    @field_validator("text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("text must not be blank")
        return value
