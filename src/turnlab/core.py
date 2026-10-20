"""Versioned fixture contracts and objective grading; no model calls or inference."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from uuid import uuid4


class ContractError(ValueError):
    """Input does not satisfy the supported scenario contract."""


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{label} must be an object")
    return value


def require_keys(value: dict[str, Any], keys: set[str], label: str) -> None:
    if set(value) != keys:
        raise ContractError(f"{label} requires exactly these fields: {', '.join(sorted(keys))}")


def require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(f"{label} must be a nonempty string")
    return value


@dataclass(frozen=True)
class Scenario:
    id: str
    name: str
    events: tuple[dict[str, Any], ...]
    final_state: dict[str, Any]
    assertions: tuple[dict[str, Any], ...]

    @classmethod
    def parse(cls, raw: Any) -> Scenario:
        data = require_object(raw, "scenario")
        require_keys(data, {"schema_version", "id", "name", "mode", "events", "final_state", "assertions"}, "scenario")
        if type(data["schema_version"]) is not int or data["schema_version"] != 1:
            raise ContractError("unsupported schema_version; expected 1")
        if data["mode"] != "fixture":
            raise ContractError("only fixture mode is implemented; text/audio modes are not measured")
        scenario_id = require_text(data["id"], "id")
        if not all(c.isascii() and (c.isalnum() or c in "-_") for c in scenario_id):
            raise ContractError("id must contain only ASCII letters, digits, hyphens, or underscores")
        name = require_text(data["name"], "name")
        if not isinstance(data["events"], list):
            raise ContractError("events must be a list")
        previous_offset = -1.0
        events: list[dict[str, Any]] = []
        for index, raw_event in enumerate(data["events"]):
            event = require_object(raw_event, f"event {index}")
            require_keys(event, {"type", "offset_ms", "data"}, f"event {index}")
            if not isinstance(event["type"], str) or event["type"] not in {"tool_call", "tool_result", "memory_read", "memory_write", "message"}:
                raise ContractError(f"unsupported event type at index {index}")
            offset = event["offset_ms"]
            if type(offset) not in (int, float) or not 0 <= offset < float("inf") or offset < previous_offset:
                raise ContractError("event offsets must be finite, nonnegative, and ordered")
            previous_offset = offset
            payload = require_object(event["data"], f"event {index} data")
            if event["type"] == "tool_call":
                require_keys(payload, {"name", "arguments"}, "tool_call data")
                require_text(payload["name"], "tool name")
                require_object(payload["arguments"], "tool arguments")
            if event["type"] in {"memory_read", "memory_write"}:
                require_keys(payload, {"tenant_id", "user_id", "key", "value"}, "memory event data")
                for key in ("tenant_id", "user_id", "key"):
                    require_text(payload[key], f"memory {key}")
            events.append(event)
        state = require_object(data["final_state"], "final_state")
        if not isinstance(data["assertions"], list) or not data["assertions"]:
            raise ContractError("assertions must be a nonempty list")
        assertions: list[dict[str, Any]] = []
        ids: set[str] = set()
        for raw_assertion in data["assertions"]:
            assertion = require_object(raw_assertion, "assertion")
            kind = assertion.get("kind")
            fields = {
                "tool_called": {"id", "kind", "name", "arguments", "count"},
                "state_equals": {"id", "kind", "key", "expected"},
                "memory_isolation": {"id", "kind", "tenant_id", "user_id"},
            }
            if not isinstance(kind, str) or kind not in fields:
                raise ContractError("unsupported assertion kind")
            require_keys(assertion, fields[kind], "assertion")
            assertion_id = require_text(assertion["id"], "assertion id")
            if assertion_id in ids:
                raise ContractError("assertion ids must be unique")
            ids.add(assertion_id)
            if kind == "tool_called":
                require_text(assertion["name"], "expected tool name")
                require_object(assertion["arguments"], "expected tool arguments")
                if type(assertion["count"]) is not int or assertion["count"] < 0:
                    raise ContractError("expected tool count must be a nonnegative integer")
            elif kind == "state_equals":
                require_text(assertion["key"], "state key")
            else:
                require_text(assertion["tenant_id"], "expected tenant_id")
                require_text(assertion["user_id"], "expected user_id")
            assertions.append(assertion)
        return cls(scenario_id, name, tuple(events), state, tuple(assertions))

    @classmethod
    def load(cls, path: Path) -> Scenario:
        try:
            return cls.parse(json.loads(path.read_text(encoding="utf-8")))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ContractError(f"invalid JSON scenario: {path.name}") from exc


def grade(scenario: Scenario) -> dict[str, Any]:
    """Inspect supplied fixture evidence. Does not execute or replay a real agent."""
    checks: list[dict[str, Any]] = []
    for assertion in scenario.assertions:
        kind = assertion["kind"]
        if kind == "tool_called":
            indexes = [i for i, e in enumerate(scenario.events)
                       if e["type"] == "tool_call" and e["data"]["name"] == assertion["name"]
                       and e["data"]["arguments"] == assertion["arguments"]]
            passed = len(indexes) == assertion["count"]
            actual: Any = {"matching_calls": len(indexes)}
            expected: Any = {"matching_calls": assertion["count"]}
        elif kind == "state_equals":
            indexes = []
            key = assertion["key"]
            passed = key in scenario.final_state and scenario.final_state[key] == assertion["expected"]
            actual = {"present": key in scenario.final_state, "value": scenario.final_state.get(key)}
            expected = {"present": True, "value": assertion["expected"]}
        else:
            indexes = [i for i, e in enumerate(scenario.events)
                       if e["type"] in {"memory_read", "memory_write"}
                       and (e["data"]["tenant_id"] != assertion["tenant_id"]
                            or e["data"]["user_id"] != assertion["user_id"])]
            passed = not indexes
            actual = {"out_of_scope_events": len(indexes)}
            expected = {"out_of_scope_events": 0}
        checks.append({"id": assertion["id"], "kind": kind, "passed": passed,
                       "expected": expected, "actual": actual, "event_indexes": indexes})
    return {
        "schema_version": 1, "id": str(uuid4()), "scenario_id": scenario.id,
        "scenario_name": scenario.name, "mode": "fixture",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if all(c["passed"] for c in checks) else "failed",
        "checks": checks, "events": list(scenario.events), "final_state": scenario.final_state,
        "metrics": {k: {"status": "not_measured", "value": None}
                    for k in ("wer", "caller_response_delay_ms", "interruption_stop_delay_ms", "cost")},
        "coverage": "Supplied fixture evidence only; no agent or speech provider was executed.",
    }
