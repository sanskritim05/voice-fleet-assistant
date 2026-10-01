"""Incident and conversation storage.

Two backends behind one interface:
- FileBackend: a JSON file plus in-process conversations. Used locally.
- RedisBackend: Upstash Redis over its REST API. Used on serverless hosts such as
  Vercel, where the filesystem is temporary and each request may hit a new instance.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import requests

from app import config

logger = logging.getLogger(__name__)

CONVERSATION_TTL_SECONDS = 60 * 60 * 6


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FileBackend:
    name = "file"

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._conversations: dict[str, tuple[float, dict]] = {}

    def _read(self) -> list[dict]:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as file:
                data = json.load(file)
        except json.JSONDecodeError:
            logger.error("Issue log at %s is not valid JSON; starting with an empty log", self.path)
            return []
        return data if isinstance(data, list) else []

    def _write(self, issues: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(issues, file, indent=2)
        os.replace(tmp_path, self.path)

    def put_issue(self, issue: dict) -> None:
        with self._lock:
            issues = [existing for existing in self._read() if existing.get("issue_id") != issue["issue_id"]]
            issues.append(issue)
            self._write(issues)

    def get_issue(self, issue_id: str) -> dict | None:
        with self._lock:
            return next((issue for issue in self._read() if issue.get("issue_id") == issue_id), None)

    def all_issues(self) -> list[dict]:
        with self._lock:
            return self._read()

    def clear_issues(self) -> None:
        with self._lock:
            self._write([])

    def put_conversation(self, conversation_id: str, data: dict) -> None:
        with self._lock:
            self._conversations[conversation_id] = (time.time() + CONVERSATION_TTL_SECONDS, data)
            expired = [key for key, (expires, _) in self._conversations.items() if expires < time.time()]
            for key in expired:
                del self._conversations[key]

    def get_conversation(self, conversation_id: str) -> dict | None:
        with self._lock:
            entry = self._conversations.get(conversation_id)
        if not entry or entry[0] < time.time():
            return None
        return json.loads(json.dumps(entry[1]))  # copy, like a real store would return


class RedisBackend:
    name = "redis"
    ISSUES_KEY = "fleetvoice:issues"
    CONVERSATION_PREFIX = "fleetvoice:conversation:"

    def __init__(self, url: str, token: str):
        self.url = url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}"}

    def _command(self, *args):
        response = requests.post(self.url, headers=self.headers, json=[str(arg) for arg in args], timeout=10)
        response.raise_for_status()
        body = response.json()
        if "error" in body:
            raise RuntimeError(f"Redis error: {body['error']}")
        return body.get("result")

    def put_issue(self, issue: dict) -> None:
        self._command("HSET", self.ISSUES_KEY, issue["issue_id"], json.dumps(issue))

    def get_issue(self, issue_id: str) -> dict | None:
        raw = self._command("HGET", self.ISSUES_KEY, issue_id)
        return json.loads(raw) if raw else None

    def all_issues(self) -> list[dict]:
        flat = self._command("HGETALL", self.ISSUES_KEY) or []
        return [json.loads(value) for value in flat[1::2]]

    def clear_issues(self) -> None:
        self._command("DEL", self.ISSUES_KEY)

    def put_conversation(self, conversation_id: str, data: dict) -> None:
        self._command("SET", self.CONVERSATION_PREFIX + conversation_id, json.dumps(data), "EX", CONVERSATION_TTL_SECONDS)

    def get_conversation(self, conversation_id: str) -> dict | None:
        raw = self._command("GET", self.CONVERSATION_PREFIX + conversation_id)
        return json.loads(raw) if raw else None


_backends: dict[tuple, object] = {}


def backend():
    """Pick the backend from current config (looked up per call so tests can repoint it)."""
    if config.REDIS_REST_URL and config.REDIS_REST_TOKEN:
        key = ("redis", config.REDIS_REST_URL)
        if key not in _backends:
            _backends[key] = RedisBackend(config.REDIS_REST_URL, config.REDIS_REST_TOKEN)
    else:
        key = ("file", str(config.ISSUES_FILE))
        if key not in _backends:
            _backends[key] = FileBackend(config.ISSUES_FILE)
    return _backends[key]


def storage_mode() -> str:
    if config.REDIS_REST_URL and config.REDIS_REST_TOKEN:
        return "redis"
    return "ephemeral" if config.ON_VERCEL else "file"


# ---------- Incidents ----------


def save_issue(
    transcript: str,
    driver_id: str,
    truck_id: str,
    category: str,
    severity: str,
    decision: str,
    actions: list[str],
    source: str = "rules",
    timestamp: str | None = None,
    status: str = "open",
    **extra,
) -> str:
    issue_id = uuid.uuid4().hex[:8]
    backend().put_issue(
        {
            "issue_id": issue_id,
            "timestamp": timestamp or now_iso(),
            "driver_id": driver_id,
            "truck_id": truck_id,
            "transcript": transcript,
            "category": category,
            "severity": severity,
            "decision": decision,
            "actions": actions,
            "source": source,
            "status": status,
            **extra,
        }
    )
    return issue_id


def get_issue(issue_id: str) -> dict | None:
    return backend().get_issue(issue_id)


def update_issue(issue_id: str, **fields) -> dict | None:
    issue = backend().get_issue(issue_id)
    if issue is None:
        return None
    issue.update(fields)
    issue["updated_at"] = now_iso()
    backend().put_issue(issue)
    return issue


def update_issue_status(issue_id: str, status: str) -> dict | None:
    return update_issue(issue_id, status=status)


def get_issues(
    severity: str | None = None,
    status: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Return issues newest first, optionally filtered."""
    issues = backend().all_issues()
    for issue in issues:
        issue.setdefault("status", "open")
        issue.setdefault("source", "rules")

    issues.sort(key=lambda issue: issue.get("timestamp", ""), reverse=True)
    if severity:
        issues = [issue for issue in issues if issue.get("severity") == severity]
    if status:
        issues = [issue for issue in issues if issue.get("status") == status]
    if limit:
        issues = issues[:limit]
    return issues


def get_stats() -> dict:
    issues = get_issues()
    unresolved = [issue for issue in issues if issue["status"] != "resolved"]
    return {
        "total": len(issues),
        "open_critical": sum(1 for issue in unresolved if issue.get("severity") == "critical"),
        "open_warning": sum(1 for issue in unresolved if issue.get("severity") == "warning"),
        "resolved": len(issues) - len(unresolved),
        "trucks_affected": len({issue.get("truck_id") for issue in unresolved}),
        "by_category": dict(Counter(issue.get("category", "general") for issue in issues)),
        "by_severity": dict(Counter(issue.get("severity", "low") for issue in issues)),
    }


def clear_issues() -> None:
    backend().clear_issues()


# ---------- Conversations ----------


def save_conversation(conversation: dict) -> None:
    backend().put_conversation(conversation["id"], conversation)


def load_conversation(conversation_id: str) -> dict | None:
    return backend().get_conversation(conversation_id)
