"""Local LiveKit reference agent with instrumented, isolated demo tools."""

import asyncio
import logging
import os
from uuid import uuid4

from dotenv import load_dotenv
from livekit import agents
from livekit.agents import Agent, AgentServer, AgentSession, function_tool
from livekit.plugins import deepgram, groq, silero

from turnlab.monitoring import ToolMonitor
from turnlab.recording import SessionRecorder
from turnlab.reference_tools import ReferenceTools
from turnlab.settings import VoiceSettings
from turnlab.storage import ReportStore
from turnlab.telemetry import configure_tracing, flush_tracing

logger = logging.getLogger(__name__)


class MonitoredAssistant(Agent):
    def __init__(self, tools: ReferenceTools):
        super().__init__(instructions=(
            "You are TurnLab's voice monitoring demonstration assistant. Keep replies brief. "
            "All tickets and bookings are isolated test fixtures, never real customer actions. "
            "When asked for ticket status, call lookup_demo_ticket; the only ticket is DEMO-001. "
            "When explicitly asked to run the booking timeout demonstration, call demonstrate_booking_timeout. "
            "If an operation returns uncertain, explain its outcome is unknown and review is needed. "
            "Never claim a booking succeeded or a human was contacted without a successful tool result. "
            "Do not repeat an unresolved booking or invent status, incident details, or root causes."
        ))
        self.reference_tools = tools

    @function_tool
    async def lookup_demo_ticket(self, ticket_id: str) -> dict:
        """Look up isolated fixture ticket DEMO-001. Use the caller's requested ticket ID."""
        return await self.reference_tools.lookup_ticket(ticket_id)

    @function_tool
    async def demonstrate_booking_timeout(self) -> dict:
        """Run a simulated uncertain-write demo only when explicitly requested. No real booking is created."""
        return await self.reference_tools.demonstrate_booking()


def build_session(settings: VoiceSettings, *, vad=None) -> AgentSession:
    settings.validate_credentials()
    return AgentSession(
        stt=deepgram.STT(model=settings.stt_model, language=settings.stt_language, api_key=settings.deepgram_api_key),
        llm=groq.LLM(model=settings.llm_model, api_key=settings.groq_api_key, parallel_tool_calls=False),
        tts=deepgram.TTS(model=settings.tts_model, api_key=settings.deepgram_api_key),
        vad=vad if vad is not None else silero.VAD.load(),
        turn_handling={"turn_detection": "vad", "interruption": {"mode": "vad"},
                       "preemptive_generation": {"enabled": False}},
        max_tool_steps=3,
    )


def attach_session_events(session: AgentSession, recorder: SessionRecorder) -> None:
    @session.on("agent_state_changed")
    def on_agent_state(event):
        recorder.capture("agent_state", state=event.new_state)

    @session.on("user_state_changed")
    def on_user_state(event):
        recorder.capture("user_state", state=event.new_state)

    @session.on("conversation_item_added")
    def on_item(event):
        # Timings only: LiveKit's per-turn ChatMessage.metrics. Message text is never read.
        item = event.item
        metrics = getattr(item, "metrics", None) or {}

        def ms(key):
            value = metrics.get(key)
            return value * 1000 if isinstance(value, (int, float)) and value >= 0 else None

        role = getattr(item, "role", None)
        if role == "assistant":
            recorder.capture("agent_reply", wait_ms=ms("e2e_latency"), llm_ms=ms("llm_node_ttft"),
                             tts_ms=ms("tts_node_ttfb"), interrupted=bool(getattr(item, "interrupted", False)))
        elif role == "user":
            recorder.capture("caller_turn", stt_ms=ms("transcription_delay"), end_of_turn_ms=ms("end_of_turn_delay"))

    @session.on("agent_false_interruption")
    def on_false_interruption(event):
        recorder.capture("false_interruption", resumed=bool(getattr(event, "resumed", False)))

    @session.on("error")
    def on_error(event):
        recorder.capture("provider_error", source=type(event.source).__name__,
                         error_type=type(event.error).__name__,
                         recoverable=bool(getattr(event.error, "recoverable", False)))

    @session.on("close")
    def on_close(event):
        reason = event.reason.value
        recorder.capture("session_closed", reason=reason)
        recorder.status = "failed" if reason == "error" else "closed"


async def entrypoint(ctx: agents.JobContext) -> None:
    settings = VoiceSettings.from_env(os.environ)
    settings.validate_credentials()
    configure_tracing(settings.otel_endpoint, include_conversation=settings.otel_include_conversation)
    monitor = ToolMonitor(str(uuid4()))
    recorder = SessionRecorder(monitor, ReportStore(settings.artifact_dir), room_name=ctx.room.name,
                               slow_reply_ms=settings.slow_reply_ms)
    recorder.start()

    async def save_on_shutdown():
        await recorder.close(status="failed" if recorder.status == "failed" else "closed")
        await asyncio.to_thread(flush_tracing)

    ctx.add_shutdown_callback(save_on_shutdown)
    logger.info("TurnLab session started; report_id=%s", monitor.session_id)
    try:
        vad = await asyncio.to_thread(silero.VAD.load)
        session = build_session(settings, vad=vad)
        attach_session_events(session, recorder)
        await ctx.connect()
        await session.start(room=ctx.room, agent=MonitoredAssistant(ReferenceTools(monitor, inject_faults=settings.demo_faults)), record=False)
        await session.generate_reply(instructions="Introduce this as a test assistant. Invite a request for ticket DEMO-001 status.")
    except BaseException as exc:
        recorder.capture("startup_failed", error_type=type(exc).__name__)
        await recorder.close(status="failed")
        raise


def create_server(settings: VoiceSettings) -> AgentServer:
    server = AgentServer(ws_url=settings.livekit_url, api_key=settings.livekit_api_key,
                         api_secret=settings.livekit_api_secret, num_idle_processes=0, host="127.0.0.1")
    server.rtc_session(entrypoint)
    return server


def main() -> None:
    load_dotenv()
    settings = VoiceSettings.from_env(os.environ)
    # The SDK CLI resolves standard LIVEKIT_* variables again and can override
    # server constructor values. Bind these to our explicit local profile first.
    os.environ["LIVEKIT_URL"] = settings.livekit_url
    os.environ["LIVEKIT_API_KEY"] = settings.livekit_api_key
    os.environ["LIVEKIT_API_SECRET"] = settings.livekit_api_secret
    agents.cli.run_app(create_server(settings))
