"""Instrument tool execution with bounded evidence and explicit recovery rules.

This module has no LiveKit dependency. A voice adapter can wrap trusted tool
implementations with it; imported traces cannot execute tools through this API.
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
import math
from time import monotonic
from typing import Any, Awaitable, Callable
from uuid import uuid4

from turnlab.telemetry import annotate_tool_attempt


class ReplaySafety(StrEnum):
    UNSAFE = "unsafe"
    READ_ONLY = "read_only"
    IDEMPOTENT_WRITE = "idempotent_write"


@dataclass(frozen=True)
class ToolPolicy:
    name: str
    replay_safety: ReplaySafety = ReplaySafety.UNSAFE
    timeout_seconds: float = 5
    max_retries: int = 0

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("tool name must be nonempty")
        if not isinstance(self.replay_safety, ReplaySafety):
            raise ValueError("replay_safety must be a ReplaySafety value")
        if type(self.timeout_seconds) not in (int, float) or not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        if type(self.max_retries) is not int or not 0 <= self.max_retries <= 3:
            raise ValueError("max_retries must be between 0 and 3")


@dataclass(frozen=True)
class ToolContext:
    operation_id: str
    attempt: int
    idempotency_key: str | None


@dataclass(frozen=True)
class ToolOutcome:
    status: str
    attempts: int
    value: Any = None
    incident_ids: tuple[str, ...] = ()


class ToolMonitor:
    """One monitor per call, used on a single asyncio event loop.

    Tool callbacks must be asynchronous and cancellation-cooperative. External
    writes can commit despite cancellation; timeout does not prove rollback.
    """

    def __init__(self, session_id: str, *, max_call_retries: int = 3, evidence_limit: int = 100):
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("session_id must be nonempty")
        if type(max_call_retries) is not int or max_call_retries < 0:
            raise ValueError("max_call_retries must be nonnegative")
        if type(evidence_limit) is not int or evidence_limit < 1:
            raise ValueError("evidence_limit must be positive")
        self.session_id = session_id
        self.max_call_retries = max_call_retries
        self.retries_used = 0
        self.events: deque[dict[str, Any]] = deque(maxlen=evidence_limit)
        self.incidents: deque[dict[str, Any]] = deque(maxlen=evidence_limit)
        self.dropped_events = 0
        self.dropped_incidents = 0
        self._started = monotonic()
        self._sequence = 0

    def elapsed_ms(self) -> float:
        """Shared monotonic origin for tool and SDK session evidence."""
        return round((monotonic() - self._started) * 1000, 3)

    def _emit(self, kind: str, operation_id: str, tool: str, attempt: int) -> str:
        self._sequence += 1
        event_id = f"{self.session_id}:{self._sequence}"
        if len(self.events) == self.events.maxlen:
            self.dropped_events += 1
        self.events.append({"id": event_id, "session_id": self.session_id,
                            "operation_id": operation_id, "type": kind,
                            "tool": tool, "attempt": attempt,
                            "offset_ms": self.elapsed_ms()})
        annotate_tool_attempt(self.events[-1])
        return event_id

    def _incident(self, policy: ToolPolicy, operation_id: str, attempt: int,
                  event_id: str, timed_out: bool, exception: Exception) -> dict[str, Any]:
        if len(self.incidents) == self.incidents.maxlen:
            self.dropped_incidents += 1
        incident = {"id": str(uuid4()), "session_id": self.session_id,
                    "operation_id": operation_id, "tool": policy.name, "attempt": attempt,
                    "kind": "tool_timeout" if timed_out else "tool_error",
                    "error_type": type(exception).__name__, "evidence_event_id": event_id,
                    "observed": "Tool reported a timeout or exceeded its deadline" if timed_out else "Tool raised an exception",
                    "cause": "unknown", "recovery": "none", "recovery_outcome": "not_attempted"}
        # Do not copy exception messages or tool arguments: they may contain secrets.
        self.incidents.append(incident)
        return incident

    async def execute(self, policy: ToolPolicy, operation: Callable[[ToolContext], Awaitable[Any]],
                      *, idempotency_key: str | None = None) -> ToolOutcome:
        if idempotency_key is not None and (not isinstance(idempotency_key, str) or not idempotency_key.strip()):
            raise ValueError("idempotency_key must be nonempty when provided")
        operation_id = str(uuid4())
        incidents: list[dict[str, Any]] = []
        for attempt in range(1, policy.max_retries + 2):
            self._emit("tool_started", operation_id, policy.name, attempt)
            try:
                value = await asyncio.wait_for(
                    operation(ToolContext(operation_id, attempt, idempotency_key)),
                    timeout=policy.timeout_seconds,
                )
            except asyncio.CancelledError:
                self._emit("tool_cancelled", operation_id, policy.name, attempt)
                for incident in incidents:
                    incident["recovery_outcome"] = "cancelled"
                raise
            except Exception as exc:
                timed_out = isinstance(exc, TimeoutError)
                event_id = self._emit("tool_timeout" if timed_out else "tool_error", operation_id, policy.name, attempt)
                incident = self._incident(policy, operation_id, attempt, event_id, timed_out, exc)
                incidents.append(incident)
                transient = isinstance(exc, (TimeoutError, ConnectionError))
                replay_safe = policy.replay_safety == ReplaySafety.READ_ONLY or (
                    policy.replay_safety == ReplaySafety.IDEMPOTENT_WRITE and idempotency_key is not None)
                # Reserve the shared retry budget before the next await.
                can_retry = transient and replay_safe and attempt <= policy.max_retries and self.retries_used < self.max_call_retries
                annotate_tool_attempt({"tool": policy.name, "attempt": attempt, "operation_id": operation_id},
                                      replay_safety=policy.replay_safety.value,
                                      decision="retry" if can_retry else "request_human_review")
                if can_retry:
                    self.retries_used += 1
                    incident["recovery"] = "retry"
                    incident["recovery_outcome"] = "pending"
                    continue
                for previous in incidents:
                    if previous["recovery"] == "retry":
                        previous["recovery_outcome"] = "unsuccessful"
                incident["recovery"] = "request_human_review"
                # The monitor requests review; it does not claim a human was reached.
                uncertain = policy.replay_safety != ReplaySafety.READ_ONLY and any(
                    i["kind"] == "tool_timeout" or i["error_type"] == "ConnectionError" for i in incidents)
                return ToolOutcome("uncertain" if uncertain else "failed", attempt,
                                   incident_ids=tuple(i["id"] for i in incidents))
            else:
                self._emit("tool_succeeded", operation_id, policy.name, attempt)
                for incident in incidents:
                    incident["recovery_outcome"] = "recovered"
                return ToolOutcome("succeeded", attempt, value, tuple(i["id"] for i in incidents))
        raise AssertionError("unreachable retry loop")

    def snapshot(self) -> dict[str, Any]:
        # Return independent JSON-compatible data, not mutable internal incident dicts.
        return {"session_id": self.session_id, "events": [dict(e) for e in self.events],
                "incidents": [dict(i) for i in self.incidents], "retries_used": self.retries_used,
                "telemetry": {"dropped_events": self.dropped_events, "dropped_incidents": self.dropped_incidents,
                              "complete": not (self.dropped_events or self.dropped_incidents)}}


async def run_monitor_demo() -> dict[str, Any]:
    """Execute real async fixture callbacks, not a live voice call or provider test."""
    monitor = ToolMonitor(str(uuid4()))
    calls = 0
    committed_bookings = 0

    async def lookup(context: ToolContext):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("injected transient lookup failure")
        return {"ticket_status": "scheduled"}

    async def book(context: ToolContext):
        nonlocal committed_bookings
        committed_bookings += 1
        raise TimeoutError("injected missing acknowledgement after commit")

    lookup_result = await monitor.execute(ToolPolicy("lookup_ticket", ReplaySafety.READ_ONLY, max_retries=1), lookup)
    booking_result = await monitor.execute(ToolPolicy("book_visit", max_retries=2), book)
    snapshot = monitor.snapshot()
    return {"schema_version": 1, "id": monitor.session_id, "mode": "tool_fixture_execution",
            "created_at": datetime.now(timezone.utc).isoformat(), "status": "completed",
            "coverage": "Async fixture tools only; no LiveKit call, cloud provider, or speech measurement.",
            "operations": {"lookup": asdict(lookup_result), "booking": asdict(booking_result)},
            "committed_bookings": committed_bookings, **snapshot}
