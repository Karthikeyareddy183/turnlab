"""Bounded session metadata and periodic disk persistence, away from audio hooks."""

import asyncio
from collections import deque
from datetime import datetime, timezone
import logging
from typing import Any

from turnlab.monitoring import ToolMonitor
from turnlab.storage import ReportStore

logger = logging.getLogger(__name__)


TEXT_FIELDS = {"source", "error_type", "state", "reason"}
FLAG_FIELDS = {"recoverable", "interrupted", "resumed"}
# Millisecond timings copied from LiveKit's per-turn ChatMessage.metrics; never text.
TIMING_FIELDS = {"wait_ms", "llm_ms", "tts_ms", "stt_ms", "end_of_turn_ms"}


class SessionRecorder:
    def __init__(self, monitor: ToolMonitor, store: ReportStore, *, room_name: str = "", event_limit: int = 100,
                 slow_reply_ms: float = 2000):
        if type(event_limit) is not int or event_limit < 1:
            raise ValueError("event_limit must be positive")
        if type(slow_reply_ms) not in (int, float) or not 0 < slow_reply_ms < float("inf"):
            raise ValueError("slow_reply_ms must be finite and positive")
        self.monitor = monitor
        self.store = store
        self.room_name = room_name
        self.slow_reply_ms = slow_reply_ms
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.status = "active"
        self.events: deque[dict[str, Any]] = deque(maxlen=event_limit)
        self.dropped_events = 0
        self.persistence_errors = 0
        self._sequence = 0
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None
        self._logged_incidents: dict[str, str] = {}

    def capture(self, kind: str, **metadata: str | bool | float | None) -> None:
        """Caller supplies allowlisted metadata, never full SDK error objects or text."""
        if set(metadata) - TEXT_FIELDS - FLAG_FIELDS - TIMING_FIELDS:
            raise ValueError("unsupported session metadata field")
        metadata = {key: value for key, value in metadata.items() if value is not None}
        for key in TIMING_FIELDS & set(metadata):
            value = metadata[key]
            if type(value) not in (int, float) or not 0 <= value < float("inf"):
                raise ValueError(f"{key} must be a finite, nonnegative number")
            metadata[key] = round(value, 1)
        for key in FLAG_FIELDS & set(metadata):
            metadata[key] = bool(metadata[key])
        if len(self.events) == self.events.maxlen:
            self.dropped_events += 1
        self._sequence += 1
        self.events.append({"id": f"{self.monitor.session_id}:session:{self._sequence}",
                            "type": kind, "offset_ms": self.monitor.elapsed_ms(), **metadata})

    def report(self) -> dict[str, Any]:
        snapshot = self.monitor.snapshot()
        provider_incidents = [{"id": e["id"], "kind": "provider_error", "evidence_event_id": e["id"],
                               "source": e.get("source", "unknown"), "error_type": e.get("error_type", "unknown"),
                               "cause": "unknown", "recovery": "sdk_managed" if e.get("recoverable") else "none"}
                              for e in self.events if e["type"] == "provider_error"]
        snapshot["incidents"] += provider_incidents
        slow = [e for e in self.events if e["type"] == "agent_reply" and e.get("wait_ms", 0) > self.slow_reply_ms]
        if slow:
            # One incident per call keeps the list readable; each slow reply stays in the evidence.
            replies = sum(e["type"] == "agent_reply" and "wait_ms" in e for e in self.events)
            worst = max(slow, key=lambda e: e["wait_ms"])
            snapshot["incidents"].append({
                "id": f"{self.monitor.session_id}:slow-replies", "kind": "slow_response", "evidence_event_id": worst["id"],
                "observed": f"{len(slow)} of {replies} replies took longer than {self.slow_reply_ms / 1000:.1f}s "
                            f"after the caller stopped speaking (slowest {worst['wait_ms'] / 1000:.1f}s).",
                "slow_replies": len(slow), "cause": "unknown", "recovery": "none", "recovery_outcome": "not_attempted"})
        snapshot["telemetry"].update(session_events_dropped=self.dropped_events, persistence_errors=self.persistence_errors)
        snapshot["telemetry"]["complete"] = snapshot["telemetry"]["complete"] and self.dropped_events == 0
        return {"schema_version": 1, "id": self.monitor.session_id, "mode": "livekit_session",
                "created_at": self.created_at, "status": self.status, "room_name": self.room_name,
                "session_events": [dict(e) for e in self.events], "audio_recorded": False,
                "transcript_recorded": False, "thresholds": {"slow_reply_ms": self.slow_reply_ms},
                "coverage": "Instrumented tools, selected SDK session/error events, and LiveKit per-turn timing; no audio-quality measurement.",
                **snapshot}

    async def flush(self) -> None:
        # Build the snapshot on the owning event loop; only disk I/O runs in a thread.
        report = self.report()
        current = {}
        for incident in report["incidents"]:
            state = incident.get("recovery_outcome", incident.get("recovery", "none"))
            current[incident["id"]] = state
            if self._logged_incidents.get(incident["id"]) != state:
                logger.warning("TurnLab incident: session=%s kind=%s recovery=%s outcome=%s",
                               self.monitor.session_id, incident["kind"], incident["recovery"], state)
        self._logged_incidents = current
        try:
            await asyncio.to_thread(self.store.save, report)
        except (OSError, ValueError):
            self.persistence_errors += 1
            logger.error("Session report persistence failed; session_id=%s", self.monitor.session_id)

    async def _pump(self) -> None:
        while not self._stop.is_set():
            await self.flush()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=1)
            except TimeoutError:
                pass

    def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("recorder already started")
        self._task = asyncio.create_task(self._pump(), name="turnlab-session-recorder")

    async def close(self, *, status: str = "closed") -> None:
        self.status = status
        self._stop.set()
        if self._task is not None:
            await self._task
        await self.flush()
