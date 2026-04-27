CRITICAL_KEYWORDS = [
    "brake",
    "brakes",
    "smoke",
    "fire",
    "blowout",
    "steering",
    "overheating",
    "engine temperature",
    "loss of power",
    "fuel leak",
    "oil pressure",
]

WARNING_KEYWORDS = [
    "check engine",
    "tire pressure",
    "vibration",
    "noise",
    "leak",
    "battery",
    "alternator",
    "coolant",
]

COMMUNICATION_KEYWORDS = [
    "dispatch",
    "delayed",
    "late",
    "eta",
    "customer",
    "message",
    "notify",
]


def classify_category(text: str) -> str:
    lowered = text.lower()

    if any(word in lowered for word in COMMUNICATION_KEYWORDS):
        return "communication"

    if "tire" in lowered or "pressure" in lowered or "blowout" in lowered:
        return "tire"

    if "brake" in lowered or "brakes" in lowered:
        return "brake"

    if "engine" in lowered or "overheating" in lowered or "temperature" in lowered:
        return "engine"

    if "battery" in lowered or "alternator" in lowered:
        return "electrical"

    return "general"


def assess_severity(text: str) -> str:
    lowered = text.lower()

    if any(word in lowered for word in CRITICAL_KEYWORDS):
        return "critical"

    if any(word in lowered for word in WARNING_KEYWORDS):
        return "warning"

    return "low"


def choose_decision(category: str, severity: str) -> str:
    if severity == "critical":
        return "STOP_SAFELY"

    if severity == "warning":
        return "CONTINUE_WITH_CAUTION"

    if category == "communication":
        return "SEND_MESSAGE"

    return "LOG_ONLY"


def build_actions(category: str, severity: str, decision: str) -> list[str]:
    actions = ["Logged issue in maintenance queue"]

    if decision == "STOP_SAFELY":
        actions.append("Recommended driver pull over safely")
        actions.append("Flagged issue as urgent for dispatch")
        actions.append("Created high-priority maintenance alert")

    elif decision == "CONTINUE_WITH_CAUTION":
        actions.append("Recommended driver monitor issue")
        actions.append("Notified dispatch for follow-up")

    elif decision == "SEND_MESSAGE":
        actions.append("Prepared dispatch update")

    else:
        actions.append("Saved note for later review")

    return actions