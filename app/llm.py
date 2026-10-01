"""Thin Groq chat-completions client with rate-limit retries."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import requests

from app import config

logger = logging.getLogger(__name__)

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
MAX_RETRIES = 4

# Seconds spent waiting on rate limits, so latency measurements can exclude them.
rate_limit_wait_seconds = 0.0


class LLMError(Exception):
    pass


def _retry_after(response: requests.Response) -> float:
    header = response.headers.get("retry-after")
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    match = re.search(r"try again in ([\d.]+)s", response.text)
    return float(match.group(1)) if match else 5.0


def chat(messages: list[dict], tools: list[dict] | None = None, temperature: float = 0.2) -> dict[str, Any]:
    """Return the assistant message (content and optional tool_calls)."""
    global rate_limit_wait_seconds
    if not config.GROQ_API_KEY:
        raise LLMError("GROQ_API_KEY is not set")

    payload: dict[str, Any] = {
        "model": config.GROQ_MODEL,
        "messages": messages,
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    if config.GROQ_MODEL.startswith("openai/gpt-oss"):
        payload["reasoning_effort"] = "low"

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = requests.post(
                GROQ_CHAT_URL,
                headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
                json=payload,
                timeout=30,
            )
        except requests.RequestException as error:
            raise LLMError(f"Groq request failed: {error}") from error

        if response.status_code == 429 and attempt < MAX_RETRIES:
            wait = min(_retry_after(response), 30.0)
            logger.info("Groq rate limit hit, retrying in %.1fs", wait)
            time.sleep(wait)
            rate_limit_wait_seconds += wait
            continue
        # Groq validates tool arguments against the schema; a malformed call is
        # usually fine on a second sample, so retry before giving up.
        if response.status_code == 400 and "tool_use_failed" in response.text and attempt < MAX_RETRIES:
            logger.info("Model produced an invalid tool call, retrying")
            payload["temperature"] = min(1.0, payload["temperature"] + 0.3)
            continue
        if response.status_code >= 400:
            raise LLMError(f"Groq error {response.status_code}: {response.text[:300]}")

        message = response.json()["choices"][0]["message"]
        return {"content": message.get("content") or "", "tool_calls": message.get("tool_calls") or []}

    raise LLMError("Groq rate limit: retries exhausted")
