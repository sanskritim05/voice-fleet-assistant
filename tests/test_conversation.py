"""Agent behavior with a scripted fake LLM, so tests are deterministic and offline."""

import json

import pytest

from app import config, conversation, llm, storage


def tool_call(name, **args):
    return {"id": f"call_{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


class ScriptedLLM:
    """Returns queued responses: a str is a final reply, a list is a set of tool calls."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, messages, tools=None, temperature=0.2):
        self.calls.append(messages)
        response = self.responses.pop(0) if self.responses else "Okay."
        if isinstance(response, str):
            return {"content": response, "tool_calls": []}
        return {"content": "", "tool_calls": response}


@pytest.fixture
def fake_llm(monkeypatch):
    monkeypatch.setattr(config, "GROQ_API_KEY", "test-key")

    def install(*responses):
        scripted = ScriptedLLM(*responses)
        monkeypatch.setattr(llm, "chat", scripted)
        return scripted

    return install


def new():
    return conversation.new_conversation("driver-1", "truck-8821")


def test_rules_fallback_without_key():
    conv = new()
    result = conversation.handle_turn(conv, "My brakes are grinding")
    assert result["source"] == "rules"
    assert result["incident"]["severity"] == "critical"
    assert result["incident"]["escalated"] is True
    assert result["awaiting_answer"] is False
    issue = storage.get_issue(result["incident"]["issue_id"])
    assert issue["conversation"][0]["text"] == "My brakes are grinding"


def test_follow_up_then_log(fake_llm):
    fake_llm(
        "Which light is on?",
        [tool_call("log_incident", category="tire", severity="warning", decision="CONTINUE_WITH_CAUTION", summary="TPMS light")],
        [tool_call("escalate_to_dispatch", reason="Tire pressure light", urgency="routine")],
        "Logged it. Check the tire at your next stop.",
    )
    conv = new()
    first = conversation.handle_turn(conv, "A light came on")
    assert first["awaiting_answer"] is True
    assert first["reply"] == "Which light is on?"
    assert first["incident"] is None

    second = conversation.handle_turn(conv, "The tire pressure one")
    assert second["awaiting_answer"] is False
    assert second["incident"]["severity"] == "warning"
    assert [event["tool"] for event in second["events"]] == ["log_incident", "escalate_to_dispatch"]
    assert second["guardrail"] is None


def test_floor_raises_underrated_severity(fake_llm):
    fake_llm(
        [tool_call("log_incident", category="engine", severity="low", decision="LOG_ONLY", summary="Minor smoke")],
        [tool_call("escalate_to_dispatch", reason="Smoke", urgency="immediate")],
        "Noted.",
    )
    conv = new()
    result = conversation.handle_turn(conv, "A little smoke from the hood, it's fine")
    assert result["model_decision"]["logged_severity"] == "low"
    assert result["incident"]["severity"] == "critical"
    assert result["incident"]["decision"] == "STOP_SAFELY"
    assert result["guardrail"]["type"] == "severity_floor"
    # the model was told about the change in the tool result
    tool_message = next(m for m in conv["messages"] if m["role"] == "tool")
    assert "raised" in json.loads(tool_message["content"])["note"]


def test_critical_never_waits_on_a_question(fake_llm):
    fake_llm("How loud is the grinding?")
    conv = new()
    result = conversation.handle_turn(conv, "My brakes are grinding")
    assert result["model_decision"]["asked_question"] is True
    assert result["guardrail"]["type"] == "critical_override"
    assert result["incident"]["severity"] == "critical"
    assert result["incident"]["escalated"] is True
    assert "pull over" in result["reply"].lower()
    assert result["awaiting_answer"] is False


def test_without_floor_the_model_decides(fake_llm):
    fake_llm("How loud is the grinding?")
    conv = new()
    result = conversation.handle_turn(conv, "My brakes are grinding", safety_floor=False)
    assert result["guardrail"] is None
    assert result["awaiting_answer"] is True


def test_question_limit_forces_a_decision(fake_llm):
    fake_llm("What light?", "What color?", "Is it blinking?")
    conv = new()
    conversation.handle_turn(conv, "Something on the dash")
    conversation.handle_turn(conv, "Not sure")
    result = conversation.handle_turn(conv, "Still not sure")
    assert result["guardrail"]["type"] == "question_limit"
    assert result["incident"] is not None
    assert result["awaiting_answer"] is False


def test_escalate_before_log_is_rejected(fake_llm):
    fake_llm(
        [tool_call("escalate_to_dispatch", reason="x", urgency="routine")],
        [tool_call("log_incident", category="electrical", severity="warning", decision="CONTINUE_WITH_CAUTION", summary="Battery light")],
        [tool_call("escalate_to_dispatch", reason="Battery light", urgency="routine")],
        "Logged.",
    )
    conv = new()
    result = conversation.handle_turn(conv, "Battery light is on")
    outcomes = [(event["tool"], event["ok"]) for event in result["events"]]
    assert outcomes == [("escalate_to_dispatch", False), ("log_incident", True), ("escalate_to_dispatch", True)]
    assert result["incident"]["escalated"] is True


def test_lookup_tools(fake_llm):
    fake_llm(
        [tool_call("get_truck_service_history"), tool_call("find_nearest_repair_shop", service="tire")],
        [tool_call("log_incident", category="tire", severity="warning", decision="CONTINUE_WITH_CAUTION", summary="Low tire")],
        "There's a shop 8 miles ahead.",
    )
    conv = new()
    result = conversation.handle_turn(conv, "Tire looks low")
    summaries = [event["summary"] for event in result["events"]]
    assert summaries[0].startswith("Checked service history")
    assert "Midwest Truck & Trailer" in summaries[1]


def test_llm_failure_falls_back_to_rules(fake_llm, monkeypatch):
    def broken(*args, **kwargs):
        raise llm.LLMError("down")

    monkeypatch.setattr(llm, "chat", broken)
    result = conversation.handle_turn(new(), "Check engine light is on")
    assert result["source"] == "rules"
    assert result["incident"]["severity"] == "warning"


def test_agent_turn_endpoint(client):
    first = client.post("/api/agent/turn", json={"text": "Tell dispatch I'm running late"}).json()
    assert first["incident"]["decision"] == "SEND_MESSAGE"
    convo = client.get(f"/api/conversations/{first['conversation_id']}").json()
    assert [turn["role"] for turn in convo["transcript"]] == ["driver", "agent"]

    second = client.post("/api/agent/turn", json={"text": "About 20 minutes", "conversation_id": first["conversation_id"]})
    assert second.status_code == 200
    assert client.post("/api/agent/turn", json={"text": "hi", "conversation_id": "missing"}).status_code == 404


def test_rules_follow_up_message_is_passed_along():
    conv = new()
    conversation.handle_turn(conv, "My brakes are grinding")
    result = conversation.handle_turn(conv, "Also tell dispatch I'll be 20 minutes late")
    assert result["reply"] == conversation.default_reply("SEND_MESSAGE")
    assert [event["tool"] for event in result["events"]] == ["send_dispatch_message"]
    issue = storage.get_issue(result["incident"]["issue_id"])
    assert len(issue["actions"]) == len(set(issue["actions"])) == 3


def test_small_talk_logs_nothing(fake_llm):
    fake_llm("I can't play music, but I'm here if anything comes up with the truck.")
    result = conversation.handle_turn(new(), "Can you play some country music?")
    assert result["incident"] is None
    assert result["awaiting_answer"] is False
    assert storage.get_issues() == []


def test_unlogged_warning_is_logged_by_rules(fake_llm):
    fake_llm("Okay, keep an eye on it.")
    result = conversation.handle_turn(new(), "Check engine light is on")
    assert result["guardrail"]["type"] == "unlogged_warning"
    assert result["incident"]["severity"] == "warning"
