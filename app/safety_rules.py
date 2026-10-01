"""Deterministic, keyword-based safety rules.

These rules serve two purposes:
1. A full fallback when the LLM is unavailable.
2. A safety floor applied on top of the LLM: the model may escalate an issue,
   but it can never rate an issue below what these rules detect.
"""

import re

SEVERITY_RANK = {"low": 0, "warning": 1, "critical": 2}

CRITICAL_KEYWORDS = [
    "brake",
    "smoke",
    "smoking",
    "fire",
    "flames",
    "blowout",
    "blew out",
    "steering",
    "overheating",
    "overheat",
    "engine temperature",
    "loss of power",
    "lost power",
    "fuel leak",
    "oil pressure",
    "can't stop",
    "cannot stop",
    "jackknife",
    "wobble",
    "wobbling",
    "loose wheel",
    "lug nut",
    "sway",
    "swaying",
    # driver health
    "chest pain",
    "chest hurts",
    "can't breathe",
    "cannot breathe",
    "short of breath",
    "dizzy",
    "passing out",
    "pass out",
    "blacked out",
    "numb",
    "falling asleep",
    "nodding off",
    "seizure",
]

WARNING_KEYWORDS = [
    "check engine",
    "tire pressure",
    "low pressure",
    "vibration",
    "vibrating",
    "noise",
    "leak",
    "leaking",
    "battery",
    "alternator",
    "coolant",
    "warning light",
    "flat",
    "headlight",
    "wiper",
]

# Ordered by hazard: the first matching category wins, so a dispatch
# message that mentions brakes is still classified as a brake issue.
CATEGORY_KEYWORDS = [
    ("driver_health", ["chest pain", "chest hurts", "can't breathe", "cannot breathe", "short of breath", "dizzy", "passing out", "pass out", "blacked out", "numb", "falling asleep", "nodding off", "seizure", "sick", "unwell", "faint"]),
    ("brake", ["brake", "abs", "air pressure", "air line"]),
    ("tire", ["tire", "tyre", "blowout", "blew out", "flat", "tread", "psi", "tire pressure"]),
    ("engine", ["engine", "overheat", "overheating", "temperature", "coolant", "oil", "smoke", "smoking", "loss of power", "lost power", "fuel"]),
    ("electrical", ["battery", "alternator", "headlight", "lights", "fuse", "wiring", "electrical"]),
    ("communication", ["dispatch", "delayed", "delay", "late", "eta", "customer", "message", "notify", "traffic", "running behind"]),
]


# Hazards whose *absence* is reassuring ("no smoke", "not a fire"). Deliberately
# excludes things like brakes and steering: "no brakes" is the worst case.
ABSENCE_IS_SAFE = {"smoke", "smoking", "fire", "flames", "leak", "leaking", "noise", "vibration", "vibrating", "overheat", "overheating"}
_NEGATED_BEFORE = re.compile(r"\b(no|not|never|without|isn't|aren't|wasn't|weren't)\s+(a\s+|any\s+|sign\s+of\s+)?$")
_ALL_CLEAR_AFTER = re.compile(r"^\s+(is|are|seems?|feels?|looks?)\s+(totally\s+|perfectly\s+|completely\s+)?(fine|ok|okay|good|normal)\b")


def _ruled_out(text: str, keyword: str, match: re.Match) -> bool:
    """True when the driver mentions a hazard only to rule it out."""
    after = text[match.end() : match.end() + 40]
    if _ALL_CLEAR_AFTER.search(after) and not re.search(r"\bbut\b", after):
        return True  # "brakes are fine, it's the radio"
    before = text[max(0, match.start() - 25) : match.start()]
    return keyword in ABSENCE_IS_SAFE and _NEGATED_BEFORE.search(before) is not None  # "no smoke"


def _matches(text: str, keyword: str) -> bool:
    """Whole-word match that tolerates simple plurals (brake -> brakes) and skips ruled-out mentions."""
    pattern = r"\b" + re.escape(keyword) + r"(s|es)?\b"
    return any(not _ruled_out(text, keyword, match) for match in re.finditer(pattern, text))


def _contains_any(text: str, keywords: list[str]) -> bool:
    return any(_matches(text, keyword) for keyword in keywords)


def matched_keywords(text: str, severity: str) -> list[str]:
    """Which keywords drove a rule-based severity, for explaining safety interventions."""
    keywords = CRITICAL_KEYWORDS if severity == "critical" else WARNING_KEYWORDS
    lowered = text.lower()
    return [keyword for keyword in keywords if _matches(lowered, keyword)]


def classify_category(text: str) -> str:
    lowered = text.lower()
    for category, keywords in CATEGORY_KEYWORDS:
        if _contains_any(lowered, keywords):
            return category
    return "general"


def assess_severity(text: str) -> str:
    lowered = text.lower()

    if _contains_any(lowered, CRITICAL_KEYWORDS):
        return "critical"

    if _contains_any(lowered, WARNING_KEYWORDS):
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


def max_severity(a: str, b: str) -> str:
    return a if SEVERITY_RANK.get(a, 0) >= SEVERITY_RANK.get(b, 0) else b
