"""Optional OpenTelemetry export of LiveKit's built-in traces, plus TurnLab recovery annotations.

LiveKit Agents already emits standard spans for sessions, turns, model requests, tools and
speech. This module only points them at an OTLP/HTTP backend chosen by the user. Local
TurnLab reports work without it, and every helper is a no-op when OpenTelemetry is absent.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)
_provider: Any = None


def configure_tracing(endpoint: str, *, include_conversation: bool = False, exporter: Any = None) -> Any:
    """Install one tracer provider per process for LiveKit spans; returns it, or None when disabled.

    Conversation text and tool payloads are stripped in-process unless include_conversation
    is true. ``exporter`` replaces the OTLP exporter in tests.
    """
    global _provider
    if not endpoint and exporter is None:
        return None
    if _provider is not None:
        return _provider
    from livekit.agents.telemetry import set_tracer_provider
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    if exporter is None:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        exporter = OTLPSpanExporter(endpoint=endpoint, timeout=10)
    provider = TracerProvider(resource=Resource.create({"service.name": "turnlab-agent"}))
    provider.add_span_processor(BatchSpanProcessor(exporter))
    set_tracer_provider(provider, allow_pii=include_conversation)
    _provider = provider
    logger.info("TurnLab: exporting LiveKit traces via OTLP (conversation content %s)",
                "included" if include_conversation else "stripped")
    return provider


def flush_tracing(timeout_ms: int = 5000) -> None:
    if _provider is not None:
        _provider.force_flush(timeout_ms)


def annotate_tool_attempt(event: dict[str, Any], **extra: Any) -> None:
    """Attach a TurnLab attempt outcome to the active span (LiveKit's function-tool span)."""
    try:
        from opentelemetry import trace
    except ImportError:
        return
    span = trace.get_current_span()
    if not span.is_recording():
        return
    attributes = {f"turnlab.{key}": value for key, value in {**event, **extra}.items()
                  if key in {"tool", "attempt", "type", "operation_id", "replay_safety", "decision"}
                  and isinstance(value, (str, int, float, bool))}
    span.add_event("turnlab.tool_attempt", attributes)
