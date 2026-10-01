from app import agent


def test_falls_back_to_rules_without_api_key():
    result = agent.generate_response("My brakes are grinding")
    assert result["source"] == "rules"
    assert result["decision"] == "STOP_SAFELY"
    assert result["severity"] == "critical"


def test_normalize_rejects_values_outside_schema():
    result = agent.normalize_llm_result(
        {"category": "spaceship", "severity": "apocalyptic", "decision": "PANIC", "actions": "nope"}
    )
    assert result["category"] == "general"
    assert result["severity"] == "low"
    assert result["decision"] == "LOG_ONLY"
    assert result["actions"]
    assert result["response_text"]


def test_safety_floor_escalates_llm_underrating(monkeypatch):
    monkeypatch.setattr(agent.config, "GROQ_API_KEY", "test-key")
    monkeypatch.setattr(
        agent,
        "reason_with_groq",
        lambda transcript: agent.normalize_llm_result(
            {"category": "general", "severity": "low", "decision": "LOG_ONLY", "response_text": "All good."}
        ),
    )

    result = agent.generate_response("There is smoke coming from the engine")

    assert result["source"] == "llm"
    assert result["guardrail_applied"] is True
    assert result["severity"] == "critical"
    assert result["decision"] == "STOP_SAFELY"
    assert result["category"] == "engine"


def test_safety_floor_keeps_llm_escalation(monkeypatch):
    llm = agent.normalize_llm_result(
        {"category": "general", "severity": "critical", "decision": "STOP_SAFELY", "response_text": "Pull over."}
    )
    result = agent.apply_safety_floor("Something smells strange", llm)
    assert result["guardrail_applied"] is False
    assert result["severity"] == "critical"


def test_groq_failure_falls_back(monkeypatch):
    monkeypatch.setattr(agent.config, "GROQ_API_KEY", "test-key")

    def boom(*args, **kwargs):
        raise ConnectionError("network down")

    monkeypatch.setattr(agent.requests, "post", boom)
    result = agent.generate_response("Check engine light is on")
    assert result["source"] == "rules"
    assert result["decision"] == "CONTINUE_WITH_CAUTION"
