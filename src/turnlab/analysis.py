"""Evidence-first incident reports. No model-based causal claims or automatic edits."""

import math
from typing import Any


def tool_label(name: Any) -> str:
    """Readable label from a policy name, e.g. lookup_ticket -> Lookup ticket."""
    text = str(name or "").replace("_", " ").replace("-", " ").strip()
    return text[:1].upper() + text[1:] if text else "A tool"


def finding_title(incident: dict[str, Any]) -> str:
    kind = incident.get("kind")
    if kind == "tool_timeout":
        return f"{tool_label(incident.get('tool'))} timed out"
    if kind == "tool_error":
        return f"{tool_label(incident.get('tool'))} failed"
    if kind == "slow_response":
        return "Slow replies"
    if kind == "provider_error":
        source = incident.get("source")
        return f"Voice service error ({source})" if source and source != "unknown" else "Voice service error"
    return "Unrecognized incident"


def percentile(values: list[float], fraction: float) -> float | None:
    """Nearest-rank percentile; None for no samples."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def slow_reply_suggestion(report: dict[str, Any]) -> str:
    limit = report.get("thresholds", {}).get("slow_reply_ms", 2000)
    slow = [e for e in report.get("session_events", []) if e.get("type") == "agent_reply" and e.get("wait_ms", 0) > limit]
    llm = sum(e.get("llm_ms", 0) for e in slow)
    tts = sum(e.get("tts_ms", 0) for e in slow)
    if slow and llm and llm >= 2 * tts:
        stage = "Most of the wait was the AI model producing its first words. Try a faster model, a shorter prompt or fewer tool steps."
    elif slow and tts and tts >= 2 * llm:
        stage = "Most of the wait was speech synthesis starting. Check the TTS provider, voice model and region."
    else:
        stage = "Compare the AI model and speech timings on the slow replies in the timeline to see which stage dominates."
    return f"{stage} Tool calls inside a turn also add to the wait. The limit is TURNLAB_SLOW_REPLY_MS ({limit:.0f} ms)."


def call_summary(report: dict[str, Any]) -> dict[str, Any] | None:
    """Counts and agent-state segments derived from captured events; None for non-call runs."""
    if report.get("mode") != "livekit_session":
        return None
    session = [e for e in report.get("session_events", []) if isinstance(e.get("offset_ms"), (int, float))]
    tools = report.get("events", [])
    offsets = [e["offset_ms"] for e in [*session, *tools] if isinstance(e.get("offset_ms"), (int, float))]
    duration = max(offsets, default=0)
    segments: list[dict[str, Any]] = []
    for event in sorted((e for e in session if e["type"] == "agent_state"), key=lambda e: e["offset_ms"]):
        if segments:
            segments[-1]["end_ms"] = event["offset_ms"]
        segments.append({"state": event.get("state", "unknown"), "start_ms": event["offset_ms"], "end_ms": duration})
    thinking = [s["end_ms"] - s["start_ms"] for s in segments if s["state"] == "thinking"]
    replies = [e for e in session if e["type"] == "agent_reply"]
    waits = [e["wait_ms"] for e in replies if isinstance(e.get("wait_ms"), (int, float))]
    return {
        "duration_ms": duration,
        "caller_turns": sum(e["type"] == "user_state" and e.get("state") == "speaking" for e in session),
        # Prefer LiveKit's reply records; older reports only have agent speaking states.
        "agent_turns": len(replies) or sum(e["type"] == "agent_state" and e.get("state") == "speaking" for e in session),
        "tool_calls": sum(e.get("type") == "tool_started" and e.get("attempt") == 1 for e in tools),
        "retries": report.get("retries_used", 0),
        "provider_errors": sum(e["type"] == "provider_error" for e in session),
        "longest_thinking_ms": max(thinking, default=None),
        # Caller wait = LiveKit e2e_latency: end of caller speech to start of agent audio.
        "wait_p50_ms": percentile(waits, .5),
        "wait_p95_ms": percentile(waits, .95),
        "wait_max_ms": max(waits, default=None),
        "slow_reply_ms": report.get("thresholds", {}).get("slow_reply_ms"),
        "replies": [{"id": e["id"], "offset_ms": e["offset_ms"], **{k: e[k] for k in ("wait_ms", "llm_ms", "tts_ms") if k in e},
                     "interrupted": bool(e.get("interrupted"))} for e in replies],
        "interruptions": sum(bool(e.get("interrupted")) for e in replies),
        "false_interruptions": sum(e["type"] == "false_interruption" for e in session),
        "agent_states": segments,
        # Evicted early events shorten these counts; the dashboard shows this flag.
        "complete": report.get("telemetry", {}).get("complete", True),
    }


def analyze_report(report: dict[str, Any]) -> dict[str, Any]:
    evidence = {str(e.get("id")) for e in [*report.get("events", []), *report.get("session_events", [])] if e.get("id")}
    findings = []
    for incident in report.get("incidents", []):
        kind = incident.get("kind", "unknown")
        suggestion = {
            "tool_timeout": "Check the operation deadline and downstream status. Reconcile uncertain writes before retrying; use a verified idempotency contract for future retries.",
            "tool_error": "Inspect the failing tool and its dependency. Distinguish transient connection failures from invalid inputs before changing retry policy.",
            "provider_error": "Check provider availability, quota, and credentials. Review the provider response in trusted logs; this report deliberately omits raw error messages.",
            "slow_response": slow_reply_suggestion(report),
        }.get(kind, "Review the attached evidence before choosing a fix.")
        reference = incident.get("evidence_event_id")
        findings.append({"id": str(incident.get("id")), "kind": kind,
                         "title": finding_title(incident), "tool": incident.get("tool"),
                         "observation": incident.get("observed") or "The SDK reported a provider error.",
                         "cause_status": "not_established", "cause": None, "suggestion": suggestion,
                         "recovery": incident.get("recovery", "none"),
                         "recovery_outcome": incident.get("recovery_outcome", "not_measured"),
                         "evidence_event_id": reference, "evidence_available": reference in evidence})
    for check in report.get("checks", []):
        if check.get("passed") is False:
            findings.append({"id": "check:" + str(check["id"]), "kind": "assertion_failed",
                             "title": f"Check failed: {tool_label(check['id'])}", "tool": None,
                             "observation": f"Scenario assertion '{check['id']}' failed.", "cause_status": "not_established", "cause": None,
                             "suggestion": "Compare the expected and actual values. Reproduce the behavior against the agent before changing the implementation or expected result.",
                             "recovery": "none", "recovery_outcome": "not_attempted", "evidence_event_id": None,
                             "evidence_indexes": check.get("event_indexes", []), "evidence_available": True})
    return {"run_id": report["id"], "method": "deterministic_evidence_summary", "findings": findings,
            "call_summary": call_summary(report),
            "coverage": report.get("coverage", "Unknown coverage"),
            "limitations": ["Root causes are not established automatically.", "Suggestions require developer review; no code or prompts were changed."]}
