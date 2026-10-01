"""The Upstash Redis backend, against an in-memory fake of its REST API."""

import pytest

from app import config, storage


class FakeUpstash:
    def __init__(self):
        self.hashes, self.strings = {}, {}

    def post(self, url, headers=None, json=None, timeout=None):
        assert headers["Authorization"] == "Bearer token"
        command, *args = json
        if command == "HSET":
            self.hashes.setdefault(args[0], {})[args[1]] = args[2]
            result = 1
        elif command == "HGET":
            result = self.hashes.get(args[0], {}).get(args[1])
        elif command == "HGETALL":
            result = [item for pair in self.hashes.get(args[0], {}).items() for item in pair]
        elif command == "DEL":
            result = int(self.hashes.pop(args[0], None) is not None)
        elif command == "SET":
            self.strings[args[0]] = args[1]
            result = "OK"
        elif command == "GET":
            result = self.strings.get(args[0])
        else:
            raise AssertionError(f"unexpected command {command}")
        return FakeResponse({"result": result})


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


@pytest.fixture
def redis(monkeypatch):
    fake = FakeUpstash()
    monkeypatch.setattr(config, "REDIS_REST_URL", "https://fake.upstash.io")
    monkeypatch.setattr(config, "REDIS_REST_TOKEN", "token")
    monkeypatch.setattr(storage.requests, "post", fake.post)
    return fake


def test_redis_backend_round_trip(redis):
    assert storage.storage_mode() == "redis"
    issue_id = storage.save_issue("Brakes grinding", "d1", "t1", "brake", "critical", "STOP_SAFELY", ["Logged"])
    storage.update_issue_status(issue_id, "acknowledged")

    issues = storage.get_issues()
    assert len(issues) == 1 and issues[0]["status"] == "acknowledged"
    assert storage.get_stats()["open_critical"] == 1

    storage.save_conversation({"id": "c1", "transcript": []})
    assert storage.load_conversation("c1") == {"id": "c1", "transcript": []}
    assert storage.load_conversation("missing") is None

    storage.clear_issues()
    assert storage.get_issues() == []


def test_vercel_without_redis_is_ephemeral(monkeypatch):
    monkeypatch.setattr(config, "ON_VERCEL", True)
    assert storage.storage_mode() == "ephemeral"
