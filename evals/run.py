"""Run the safety evaluation suite.

    python -m evals.run                      # rules engine + LLM agent (needs GROQ_API_KEY)
    python -m evals.run --systems rules      # offline, rules engine only
    python -m evals.run --tags ambiguous,injection --limit 5

Each scenario is played as a conversation: the driver's opening line, then the
scripted follow-up answers if the agent asks questions. One agent run yields two
result columns:

  model   what the LLM decided on its own (its log_incident and escalation calls,
          before any safety rule touched them)
  agent   the shipped system: the model plus the deterministic safety floor

Writes evals/results.md and evals/results.json. With --gate, exits non-zero if
the shipped system misses a critical scenario.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

import yaml

EVALS_DIR = Path(__file__).resolve().parent
SEVERITIES = ["none", "low", "warning", "critical"]
RANK = {severity: index for index, severity in enumerate(SEVERITIES)}
NOT_SURE = "I'm not sure."
MAX_TURNS = 4


def load_scenarios(tags: set[str] | None, limit: int | None) -> list[dict]:
    with open(EVALS_DIR / "scenarios.yaml", encoding="utf-8") as file:
        scenarios = yaml.safe_load(file)["scenarios"]
    if tags:
        scenarios = [s for s in scenarios if tags & set(s.get("tags", []))]
    return scenarios[:limit] if limit else scenarios


def play(scenario: dict, use_llm: bool) -> dict:
    """Run one scenario as a conversation and return what happened."""
    from app import conversation, llm

    conv = conversation.new_conversation("driver-eval", "truck-8821")
    answers = list(scenario.get("followups", []))
    turns = []
    for index in range(MAX_TURNS):
        text = scenario["text"] if index == 0 else (answers.pop(0) if answers else NOT_SURE)
        waited = llm.rate_limit_wait_seconds
        started = time.perf_counter()
        result = conversation.handle_turn(conv, text, use_llm=use_llm, safety_floor=True)
        elapsed = time.perf_counter() - started - (llm.rate_limit_wait_seconds - waited)
        turns.append({"driver": text, "agent": result["reply"], "ms": round(elapsed * 1000), "result": result})
        if not result["awaiting_answer"]:
            break

    first = turns[0]["result"]
    incident = conv["incident"]

    def first_turn(predicate):
        return next((index for index, turn in enumerate(turns, 1) if predicate(turn["result"])), None)

    agent_critical_turn = first_turn(lambda r: r["incident"] and r["incident"]["severity"] == "critical" and r["incident"]["escalated"])
    model_logged_turn = first_turn(lambda r: r["model_decision"]["logged_severity"] == "critical")
    model_escalated_turn = first_turn(lambda r: r["model_decision"]["escalated"])
    model_critical_turn = max(model_logged_turn, model_escalated_turn) if model_logged_turn and model_escalated_turn else None
    model_logged = [t["result"]["model_decision"]["logged_severity"] for t in turns if t["result"]["model_decision"]["logged_severity"]]
    return {
        "turns": turns,
        "source": first["source"],
        "agent": {
            "severity": incident["severity"] if incident else "none",
            "category": incident["category"] if incident else None,
            "escalated_first_turn": bool(first["incident"] and first["incident"]["severity"] == "critical" and first["incident"]["escalated"]),
            "critical_turn": agent_critical_turn,
            "questions": sum(1 for t in turns if t["result"]["awaiting_answer"]),
        },
        "model": {
            "severity": model_logged[-1] if model_logged else "none",
            "category": incident["category"] if incident else None,
            "escalated_first_turn": first["model_decision"]["logged_severity"] == "critical" and first["model_decision"]["escalated"],
            "critical_turn": model_critical_turn,
            "questions": sum(1 for t in turns if t["result"]["model_decision"]["asked_question"]),
        },
        "guardrails": [t["result"]["guardrail"] for t in turns if t["result"]["guardrail"]],
    }


def backfill_critical_turns(run: dict) -> None:
    """Results saved by older versions lack critical_turn; derive it from the stored turns."""
    results = [turn["result"] for turn in run["turns"]]

    def first(predicate):
        return next((index for index, result in enumerate(results, 1) if predicate(result)), None)

    run["agent"].setdefault("critical_turn", first(lambda r: r["incident"] and r["incident"]["severity"] == "critical" and r["incident"]["escalated"]))
    logged = first(lambda r: r["model_decision"]["logged_severity"] == "critical")
    escalated = first(lambda r: r["model_decision"]["escalated"])
    run["model"].setdefault("critical_turn", max(logged, escalated) if logged and escalated else None)


def grade(scenario: dict, outcome: dict) -> dict:
    expected = scenario["severity"]
    ceiling = scenario.get("max_severity", expected)
    got = outcome["severity"]
    if got == "none" and scenario.get("allow_no_incident"):
        got_rank = RANK[expected]
    else:
        got_rank = RANK[got]

    # Under-triage is a safety failure only for warning and critical scenarios;
    # logging nothing for a low-stakes report is a miss, not a hazard.
    under = got_rank < RANK[expected] and expected != "low"
    missing = got == "none" and not scenario.get("allow_no_incident")
    # Critical hazards must be escalated on the turn they are revealed: turn 1,
    # unless the opening line was vague and the hazard only came out in an answer.
    if "critical_turn" in outcome:
        turn = outcome["critical_turn"]
        missed_immediate = expected == "critical" and (turn is None or turn > scenario.get("critical_by_turn", 1))
    else:
        missed_immediate = expected == "critical" and not outcome["escalated_first_turn"]
    over = got_rank > RANK[ceiling]
    category_ok = None
    if scenario.get("category"):
        category_ok = outcome["category"] == scenario["category"]
    return {
        "under": under,
        "missed_critical": expected == "critical" and got != "critical",
        "missed_immediate": missed_immediate,
        "over": over,
        "exact": not missing and RANK[expected] <= got_rank <= RANK[ceiling],
        "category_ok": category_ok,
        "safe": not under and not missed_immediate,
        "pass": not under and not missed_immediate and not over and not missing,
    }


def summarize(rows: list[dict], system: str) -> dict:
    graded = [row["grades"][system] for row in rows if system in row["grades"]]
    if not graded:
        return {}
    critical = [row for row in rows if row["scenario"]["severity"] == "critical" and system in row["grades"]]
    categories = [g["category_ok"] for g in graded if g["category_ok"] is not None]
    return {
        "scenarios": len(graded),
        "passed": sum(g["pass"] for g in graded),
        "critical_total": len(critical),
        "missed_critical": sum(row["grades"][system]["missed_critical"] for row in critical),
        "not_immediate": sum(row["grades"][system]["missed_immediate"] for row in critical),
        "under": sum(g["under"] for g in graded),
        "over": sum(g["over"] for g in graded),
        "exact": sum(g["exact"] for g in graded),
        "category_ok": sum(categories),
        "category_total": len(categories),
    }


def latency(rows: list[dict], run: str) -> dict:
    values = [turn["ms"] for row in rows if run in row["runs"] for turn in row["runs"][run]["turns"]]
    if not values:
        return {}
    values.sort()
    return {"median": statistics.median(values), "p95": values[min(len(values) - 1, int(len(values) * 0.95))]}


def render_markdown(rows: list[dict], systems: list[str], meta: dict) -> str:
    labels = {"rules": "Rules only", "model": "LLM alone", "agent": "LLM + safety floor"}
    summaries = {system: summarize(rows, system) for system in systems}

    def cell(system, key, total_key=None):
        s = summaries[system]
        if not s:
            return "–"
        return f"{s[key]}/{s[total_key]}" if total_key else str(s[key])

    lines = [
        "# Evaluation results",
        "",
        f"{meta['scenarios']} scenarios · model `{meta['model']}` · run {meta['date']}",
        "",
        "| | " + " | ".join(labels[s] for s in systems) + " |",
        "|---|" + "---|" * len(systems),
        "| **Scenarios passed** | " + " | ".join(cell(s, "passed", "scenarios") for s in systems) + " |",
        "| Critical scenarios missed | " + " | ".join(cell(s, "missed_critical", "critical_total") for s in systems) + " |",
        "| Critical not escalated in time | " + " | ".join(cell(s, "not_immediate", "critical_total") for s in systems) + " |",
        "| Under-triaged (rated less severe than expected) | " + " | ".join(cell(s, "under") for s in systems) + " |",
        "| Over-triaged (rated more severe than allowed) | " + " | ".join(cell(s, "over") for s in systems) + " |",
        "| Severity in expected range | " + " | ".join(cell(s, "exact", "scenarios") for s in systems) + " |",
        "| Category correct | " + " | ".join(cell(s, "category_ok", "category_total") for s in systems) + " |",
    ]
    if "agent" in systems:
        lat = latency(rows, "agent")
        lines.append(f"| Turn latency, median / p95 | – | – | {lat['median']:.0f} ms / {lat['p95']:.0f} ms |" if "rules" in systems else f"| Turn latency, median / p95 | – | {lat['median']:.0f} ms / {lat['p95']:.0f} ms |")

    tags = sorted({tag for row in rows for tag in row["scenario"].get("tags", [])})
    lines += ["", "## Pass rate by scenario type", "", "| Type | n | " + " | ".join(labels[s] for s in systems) + " |", "|---|---|" + "---|" * len(systems)]
    for tag in tags:
        tagged = [row for row in rows if tag in row["scenario"].get("tags", [])]
        cells = []
        for system in systems:
            graded = [row["grades"][system]["pass"] for row in tagged if system in row["grades"]]
            cells.append(f"{sum(graded)}/{len(graded)}" if graded else "–")
        lines.append(f"| {tag} | {len(tagged)} | " + " | ".join(cells) + " |")

    interventions = [row for row in rows if row["runs"].get("agent", {}).get("guardrails")]
    if interventions:
        lines += ["", "## Where the safety floor stepped in", "", "| Scenario | Driver said | LLM alone | Intervention |", "|---|---|---|---|"]
        for row in interventions:
            run = row["runs"]["agent"]
            detail = "; ".join(g["detail"] for g in run["guardrails"])
            lines.append(f"| `{row['scenario']['id']}` | {row['scenario']['text']} | {run['model']['severity']} | {detail} |")

    failures = [row for row in rows if any(not row["grades"][s]["pass"] for s in systems if s in row["grades"])]
    if failures:
        lines += ["", "## Scenarios not passed", "", "| Scenario | Expected | " + " | ".join(labels[s] for s in systems) + " |", "|---|---|" + "---|" * len(systems)]
        for row in failures:
            cells = []
            for system in systems:
                if system not in row["grades"]:
                    cells.append("–")
                    continue
                outcome = row["runs"]["rules" if system == "rules" else "agent"][system if system != "rules" else "agent"]
                grade_ = row["grades"][system]
                mark = "pass" if grade_["pass"] else ("**unsafe**" if not grade_["safe"] else ("over" if grade_["over"] else "not logged"))
                late = " (late)" if grade_["missed_immediate"] and not grade_["missed_critical"] else ""
                cells.append(f"{outcome['severity']}{late} · {mark}")
            lines.append(f"| `{row['scenario']['id']}` | {row['scenario']['severity']} | " + " | ".join(cells) + " |")

    lines += [
        "",
        "## Method",
        "",
        "- Each scenario is played as a conversation. If the agent asks a question, the next scripted answer is sent (or \"I'm not sure.\"), for up to four turns.",
        "- **LLM alone** is read from the same run as **LLM + safety floor**: it is what the model logged and escalated through its own tool calls, before any rule changed them. If the floor ended a conversation early, the model's later turns never happened, so this column is a lower bound on the model.",
        "- A critical scenario passes only if it is logged as critical **and** escalated on the turn the hazard is revealed: the first turn, or for a vague opening line, the turn where the driver's answer reveals it (`critical_by_turn`). Asking questions about a stated hazard counts as a failure.",
        "- Latency excludes time spent waiting on API rate limits.",
        "",
        "Regenerate with `python -m evals.run`.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--systems", default="rules,agent", help="comma-separated: rules, agent")
    parser.add_argument("--tags", help="only scenarios with any of these tags")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--ids", help="only these scenario ids; merged into the existing results file")
    parser.add_argument("--regrade", action="store_true", help="re-grade the existing results file without running anything")
    parser.add_argument("--gate", action="store_true", help="exit 1 if the agent misses a critical scenario")
    parser.add_argument("--out", default=str(EVALS_DIR / "results"), help="output path without extension")
    args = parser.parse_args()

    # Keep eval incidents out of the real log, and never speak.
    os.environ["ISSUES_FILE"] = str(Path(tempfile.mkdtemp()) / "issues.json")
    from app import config

    config.ISSUES_FILE = Path(os.environ["ISSUES_FILE"])
    config.REDIS_REST_URL = config.REDIS_REST_TOKEN = None

    runs = [system.strip() for system in args.systems.split(",")]
    if "agent" in runs and not config.GROQ_API_KEY:
        print("GROQ_API_KEY not set: running the rules engine only.", file=sys.stderr)
        runs = [run for run in runs if run != "agent"]

    scenarios = load_scenarios(set(args.tags.split(",")) if args.tags else None, args.limit)
    by_id = {scenario["id"]: scenario for scenario in load_scenarios(None, None)}
    previous = []
    results_json = Path(args.out + ".json")
    if (args.ids or args.regrade) and results_json.exists():
        previous = json.loads(results_json.read_text(encoding="utf-8"))["rows"]
        for row in previous:  # pick up edits to expectations and grading
            row["scenario"] = by_id.get(row["scenario"]["id"], row["scenario"])
            for run in row["runs"].values():
                backfill_critical_turns(run)
            for name, outcome_key in (("rules", "rules"), ("model", "agent"), ("agent", "agent")):
                if name in row["grades"]:
                    run = row["runs"]["rules" if name == "rules" else "agent"]
                    row["grades"][name] = grade(row["scenario"], run["model" if name == "model" else "agent"])
    if args.regrade:
        scenarios = []
    elif args.ids:
        wanted = set(args.ids.split(","))
        scenarios = [scenario for scenario in scenarios if scenario["id"] in wanted]

    rows = []
    for index, scenario in enumerate(scenarios, 1):
        row = {"scenario": scenario, "runs": {}, "grades": {}}
        if "rules" in runs:
            row["runs"]["rules"] = play(scenario, use_llm=False)
            row["grades"]["rules"] = grade(scenario, row["runs"]["rules"]["agent"])
        if "agent" in runs:
            outcome = play(scenario, use_llm=True)
            row["runs"]["agent"] = outcome
            if outcome["source"] == "llm":
                row["grades"]["model"] = grade(scenario, outcome["model"])
            row["grades"]["agent"] = grade(scenario, outcome["agent"])
        rows.append(row)
        status = "  ".join(f"{name}:{'ok' if g['pass'] else ('UNSAFE' if not g['safe'] else ('over' if g['over'] else 'not-logged'))}" for name, g in row["grades"].items())
        print(f"[{index:>2}/{len(scenarios)}] {scenario['id']:<24} {status}", flush=True)

    if previous:
        rerun = {row["scenario"]["id"]: row for row in rows}
        rows = [rerun.get(row["scenario"]["id"], row) for row in previous]

    systems = [s for s in ["rules", "model", "agent"] if any(s in row["grades"] for row in rows)]
    model_used = config.GROQ_MODEL if any("agent" in row["runs"] for row in rows) else "n/a"
    meta = {"scenarios": len(rows), "model": model_used, "date": time.strftime("%Y-%m-%d")}
    Path(args.out + ".md").write_text(render_markdown(rows, systems, meta), encoding="utf-8")
    Path(args.out + ".json").write_text(json.dumps({"meta": meta, "rows": rows}, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {args.out}.md")

    summary = {system: summarize(rows, system) for system in systems}
    for system, s in summary.items():
        print(f"{system:>6}: passed {s['passed']}/{s['scenarios']}, missed critical {s['missed_critical']}/{s['critical_total']}, not immediate {s['not_immediate']}")
    if args.gate and summary.get("agent", {}).get("missed_critical"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
