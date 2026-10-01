from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests

from app import config
from app.safety_rules import (
    SEVERITY_RANK,
    assess_severity,
    build_actions,
    choose_decision,
    classify_category,
    max_severity,
)

logger = logging.getLogger(__name__)

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
ALLOWED_DECISIONS = {"STOP_SAFELY", "CONTINUE_WITH_CAUTION", "SEND_MESSAGE", "LOG_ONLY"}
ALLOWED_SEVERITIES = {"critical", "warning", "low"}
ALLOWED_CATEGORIES = {"brake", "tire", "engine", "electrical", "driver_health", "communication", "general"}

SYSTEM_PROMPT = (
    "You are a safety-first voice fleet copilot for long-haul truck drivers. "
    "The driver cannot look at a screen, so responses must be concise, spoken, and actionable. "
    "Keep response_text under 35 words, in plain speech with no lists or symbols. "
    "Return JSON only with keys: category, severity, decision, response_text, actions. "
    "Allowed category: brake,tire,engine,electrical,driver_health,communication,general. "
    "Allowed severity: critical,warning,low. "
    "Allowed decision: STOP_SAFELY,CONTINUE_WITH_CAUTION,SEND_MESSAGE,LOG_ONLY. "
    "actions must be an array of 2-4 short past-tense strings describing what the system did."
)


def generate_response(transcript: str) -> dict[str, Any]:
    """Reason over a transcript with the LLM, then enforce the rule-based safety floor."""
    started = time.perf_counter()

    llm_result = reason_with_groq(transcript)
    if llm_result is not None:
        result = apply_safety_floor(transcript, llm_result)
        result["source"] = "llm"
        result["model"] = config.GROQ_MODEL
    else:
        result = fallback_rule_response(transcript)
        result["source"] = "rules"
        result["model"] = None

    result["reasoning_ms"] = round((time.perf_counter() - started) * 1000)
    return result


def reason_with_groq(transcript: str) -> dict[str, Any] | None:
    if not config.GROQ_API_KEY:
        return None

    user_prompt = (
        "Driver transcript:\n"
        f"{transcript}\n\n"
        "Classify and decide the safest action. Prefer conservative safety for uncertainty."
    )

    headers = {
        "Authorization": f"Bearer {config.GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.GROQ_MODEL,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
    }

    try:
        response = requests.post(GROQ_CHAT_URL, headers=headers, json=payload, timeout=25)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return normalize_llm_result(json.loads(content))
    except Exception as error:
        logger.warning("Groq reasoning failed, using fallback rules: %s", error)
        return None


def normalize_llm_result(raw: dict[str, Any]) -> dict[str, Any]:
    category = str(raw.get("category", "general")).lower()
    severity = str(raw.get("severity", "low")).lower()
    decision = str(raw.get("decision", "LOG_ONLY")).upper()

    if category not in ALLOWED_CATEGORIES:
        category = "general"
    if severity not in ALLOWED_SEVERITIES:
        severity = "low"
    if decision not in ALLOWED_DECISIONS:
        decision = "LOG_ONLY"

    response_text = str(raw.get("response_text", "")).strip()
    if not response_text:
        response_text = default_driver_response(decision)

    actions = raw.get("actions", [])
    if not isinstance(actions, list):
        actions = []
    cleaned_actions = [str(item).strip() for item in actions if str(item).strip()]
    if not cleaned_actions:
        cleaned_actions = build_actions(category, severity, decision)

    return {
        "category": category,
        "severity": severity,
        "decision": decision,
        "response_text": response_text,
        "actions": cleaned_actions[:4],
        "guardrail_applied": False,
    }


def apply_safety_floor(transcript: str, result: dict[str, Any]) -> dict[str, Any]:
    """Never let the LLM rate an issue below what the deterministic rules detect."""
    rule_severity = assess_severity(transcript)
    if SEVERITY_RANK[rule_severity] <= SEVERITY_RANK[result["severity"]]:
        return result

    severity = max_severity(result["severity"], rule_severity)
    category = result["category"]
    if category == "general":
        category = classify_category(transcript)
    decision = choose_decision(category, severity)

    return {
        **result,
        "category": category,
        "severity": severity,
        "decision": decision,
        "response_text": default_driver_response(decision),
        "actions": build_actions(category, severity, decision),
        "guardrail_applied": True,
    }


def fallback_rule_response(transcript: str) -> dict[str, Any]:
    category = classify_category(transcript)
    severity = assess_severity(transcript)
    decision = choose_decision(category, severity)
    return {
        "category": category,
        "severity": severity,
        "decision": decision,
        "response_text": default_driver_response(decision),
        "actions": build_actions(category, severity, decision),
        "guardrail_applied": False,
    }


def default_driver_response(decision: str) -> str:
    if decision == "STOP_SAFELY":
        return (
            "This sounds serious. Slow down, signal, and pull over somewhere safe now. "
            "I logged this as urgent and alerted dispatch."
        )
    if decision == "CONTINUE_WITH_CAUTION":
        return (
            "I logged the issue and notified dispatch. Continue carefully, monitor the truck, "
            "and pull over safely if it gets worse."
        )
    if decision == "SEND_MESSAGE":
        return "Understood. I logged your update and prepared a dispatch message."
    return "I logged your note for maintenance review. No urgent action is needed right now."
