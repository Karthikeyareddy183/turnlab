"""Executable isolated reference cases. Never re-label saved evidence as a rerun."""

from datetime import datetime, timezone
from hashlib import sha256
import json
from time import perf_counter
from uuid import uuid4

from turnlab.memory import ScopedMemory

SUITE_VERSION = "reference-v1"
PROFILES = {"corrected", "fault_memory", "fault_duplicate_booking"}
# These are executable requests and expected outputs, not pre-recorded event traces.
CASES = [
    {"id": "correction", "steps": [
        {"op": "remember", "value": "Thursday"}, {"op": "remember", "value": "Friday"},
        {"op": "recall", "expected": "Friday"}, {"op": "book", "key": "booking-1", "expected": {"day": "Friday", "count": 1}}]},
    {"id": "isolation", "steps": [
        {"op": "remember", "value": "Friday"}, {"op": "recall", "user": "other-user", "expected": None},
        {"op": "recall", "tenant": "other-tenant", "expected": None}]},
    {"id": "expiry-deletion", "steps": [
        {"op": "remember", "value": "Friday", "ttl": 10}, {"op": "advance", "seconds": 10},
        {"op": "recall", "expected": None}, {"op": "remember", "value": "Monday"},
        {"op": "forget"}, {"op": "recall", "expected": None}]},
    {"id": "duplicate-write", "steps": [
        {"op": "remember", "value": "Friday"}, {"op": "book", "key": "booking-1", "expected": {"day": "Friday", "count": 1}},
        {"op": "book", "key": "booking-1", "expected": {"day": "Friday", "count": 1}}]},
]


def contract_fingerprint():
    return sha256(json.dumps({"version": SUITE_VERSION, "cases": CASES}, sort_keys=True).encode()).hexdigest()


def run_suite(profile: str = "corrected") -> dict:
    if profile not in PROFILES:
        raise ValueError("Unknown reference profile")
    checks, events = [], []
    started = perf_counter()
    run_id = str(uuid4())
    for case in CASES:
        now = [0.0]
        memory = ScopedMemory(clock=lambda: now[0])
        bookings = {}
        booking_count = 0
        for index, step in enumerate(case["steps"]):
            scope = (step.get("tenant", "demo-tenant"), step.get("user", "demo-user"), "day")
            op, actual = step["op"], None
            if op == "remember":
                if profile != "fault_memory" or memory.get(*scope) is None:
                    memory.put(*scope, step["value"], ttl=step.get("ttl", 300))
            elif op == "advance":
                now[0] += step["seconds"]
            elif op == "forget":
                memory.forget(*scope)
            elif op == "recall":
                entry = memory.get(*(("demo-tenant", "demo-user", "day") if profile == "fault_memory" else scope))
                actual = entry.value if entry else None
            elif op == "book":
                entry = memory.get(*scope)
                if step["key"] not in bookings or profile == "fault_duplicate_booking":
                    booking_count += 1
                    bookings[step["key"]] = entry.value if entry else None
                actual = {"day": bookings[step["key"]], "count": booking_count}
            event_index = len(events)
            events.append({"id": f"{run_id}:{event_index}", "type": f"reference_{op}", "offset_ms": (perf_counter() - started) * 1000,
                           "case_id": case["id"], "logical_time_seconds": now[0], "actual": actual})
            if "expected" in step:
                checks.append({"id": f'{case["id"]}:{index}', "kind": "reference_output", "passed": actual == step["expected"],
                               "expected": step["expected"], "actual": actual, "event_indexes": [event_index]})
    return {"schema_version": 1, "id": run_id, "created_at": datetime.now(timezone.utc).isoformat(),
            "mode": "reference_execution", "scenario_id": SUITE_VERSION, "scenario_name": f"Reference regression · {profile}",
            "contract_fingerprint": contract_fingerprint(), "profile": profile,
            "status": "passed" if all(c["passed"] for c in checks) else "failed", "checks": checks, "events": events,
            "case_count": len(CASES), "metrics": {"wer": {"status": "not_measured", "value": None}},
            "coverage": "Executed deterministic reference controller and memory/tool operations. TTL uses a logical clock; event offsets use elapsed execution time. No LLM, speech, or LiveKit call; no caller-perceived latency measurement."}


def compare_runs(baseline: dict, candidate: dict) -> dict:
    if baseline.get('mode') not in {'reference_execution', 'agent_text_execution'} or baseline.get('mode') != candidate.get('mode'):
        raise ValueError("Comparison requires matching executable suite modes")
    if any(r.get('status') not in {'passed', 'failed'} for r in (baseline, candidate)):
        raise ValueError("Incomplete runs cannot be compared")
    if not baseline.get("contract_fingerprint") or baseline.get("contract_fingerprint") != candidate.get("contract_fingerprint"):
        raise ValueError("Runs use different evaluation contracts")
    def checks(report):
        result = {c["id"]: c for c in report["checks"]}
        if len(result) != len(report["checks"]) or not result or any(type(c.get("passed")) is not bool for c in result.values()):
            raise ValueError("Run has invalid or duplicate checks")
        return result
    old, new = checks(baseline), checks(candidate)
    if old.keys() != new.keys():
        raise ValueError("Runs have different assertion coverage")
    if any(old[k]["expected"] != new[k]["expected"] for k in old):
        raise ValueError("Runs have different assertion expectations")
    rows = [{"id": k, "baseline_passed": old[k]["passed"], "candidate_passed": new[k]["passed"],
             "change": "regressed" if old[k]["passed"] and not new[k]["passed"] else "fixed" if not old[k]["passed"] and new[k]["passed"] else "unchanged"}
            for k in old]
    return {"baseline_id": baseline["id"], "candidate_id": candidate["id"], "checks": rows,
            "regressions": sum(r["change"] == "regressed" for r in rows), "fixes": sum(r["change"] == "fixed" for r in rows),
            "remaining_failures": sum(not r["candidate_passed"] for r in rows), "contract_fingerprint": baseline["contract_fingerprint"]}


def incident_draft(report: dict) -> dict:
    """A review worksheet, deliberately not an executable or passing scenario."""
    return {"schema_version": 1, "id": str(uuid4()), "mode": "regression_draft", "review_status": "required",
            "created_at": datetime.now(timezone.utc).isoformat(), "source_run_id": report["id"],
            "source_fingerprint": sha256(json.dumps(report, sort_keys=True).encode()).hexdigest(),
            "source_incident_ids": [i["id"] for i in report.get("incidents", [])],
            "source_failed_checks": [c["id"] for c in report.get("checks", []) if c.get("passed") is False],
            "instructions": "Review the source evidence, define reproducible inputs and objective expected outputs, then implement a versioned executable case. This worksheet is never run automatically.",
            "reproduction_steps": [], "expected_outcome": None, "reviewer": None}
