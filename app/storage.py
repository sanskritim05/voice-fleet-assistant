import json
import os
import uuid
from datetime import datetime, timezone
from app.config import ISSUES_FILE


def ensure_storage_exists() -> None:
    os.makedirs(os.path.dirname(ISSUES_FILE), exist_ok=True)

    if not os.path.exists(ISSUES_FILE):
        with open(ISSUES_FILE, "w", encoding="utf-8") as file:
            json.dump([], file)


def save_issue(
    transcript: str,
    driver_id: str,
    truck_id: str,
    category: str,
    severity: str,
    decision: str,
    actions: list[str],
) -> str:
    ensure_storage_exists()

    issue_id = str(uuid.uuid4())[:8]

    issue = {
        "issue_id": issue_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "driver_id": driver_id,
        "truck_id": truck_id,
        "transcript": transcript,
        "category": category,
        "severity": severity,
        "decision": decision,
        "actions": actions,
    }

    with open(ISSUES_FILE, "r", encoding="utf-8") as file:
        issues = json.load(file)

    issues.append(issue)

    with open(ISSUES_FILE, "w", encoding="utf-8") as file:
        json.dump(issues, file, indent=2)

    return issue_id


def get_issues() -> list[dict]:
    ensure_storage_exists()

    with open(ISSUES_FILE, "r", encoding="utf-8") as file:
        return json.load(file)