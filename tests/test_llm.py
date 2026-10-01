import pytest

from app import config, llm


class Response:
    def __init__(self, status, text="", body=None, headers=None):
        self.status_code, self.text, self._body, self.headers = status, text, body, headers or {}

    def json(self):
        return self._body


OK = Response(200, body={"choices": [{"message": {"content": "Hi", "tool_calls": None}}]})


@pytest.fixture
def responses(monkeypatch):
    monkeypatch.setattr(config, "GROQ_API_KEY", "test-key")
    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)
    queue = []
    monkeypatch.setattr(llm.requests, "post", lambda *args, **kwargs: queue.pop(0))
    return queue


def test_retries_invalid_tool_call(responses):
    responses += [Response(400, text='{"error":{"code":"tool_use_failed"}}'), OK]
    assert llm.chat([{"role": "user", "content": "x"}], tools=[{}])["content"] == "Hi"


def test_waits_on_rate_limit(responses):
    before = llm.rate_limit_wait_seconds
    responses += [Response(429, text="Please try again in 2.5s"), OK]
    assert llm.chat([{"role": "user", "content": "x"}])["content"] == "Hi"
    assert llm.rate_limit_wait_seconds - before == pytest.approx(2.5)


def test_other_errors_raise(responses):
    responses.append(Response(500, text="boom"))
    with pytest.raises(llm.LLMError):
        llm.chat([{"role": "user", "content": "x"}])
