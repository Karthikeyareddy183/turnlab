import asyncio
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from turnlab.monitoring import ToolMonitor
from turnlab.recording import SessionRecorder
from turnlab.reference_tools import ReferenceTools
from turnlab.settings import VoiceSettings
from turnlab.storage import ReportStore

ROOT = Path(__file__).resolve().parents[1]


def setUpModule():
    (ROOT / ".turnlab").mkdir(exist_ok=True)


class SettingsTests(unittest.TestCase):
    def test_local_defaults_ignore_old_cloud_url(self):
        settings = VoiceSettings.from_env({"LIVEKIT_URL": "wss://old-cloud.invalid"})
        self.assertEqual(settings.livekit_url, "ws://127.0.0.1:7880")

    def test_secrets_not_in_repr_or_missing_configuration_error(self):
        settings = VoiceSettings.from_env({"GROQ_API_KEY": "private-groq-value"})
        self.assertNotIn("private-groq-value", repr(settings))
        with self.assertRaisesRegex(ValueError, "DEEPGRAM_API_KEY"):
            settings.validate_credentials()

    def test_remote_and_credential_urls_rejected(self):
        for url in ("wss://remote.invalid", "http://localhost:7880", "ws://key:secret@localhost:7880", "ws://localhost:7880?key=x"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                VoiceSettings.from_env({"TURNLAB_LIVEKIT_URL": url})

    def test_fault_flag_must_be_explicit(self):
        self.assertFalse(VoiceSettings.from_env({}).demo_faults)
        self.assertTrue(VoiceSettings.from_env({"TURNLAB_DEMO_FAULTS": "true"}).demo_faults)
        with self.assertRaises(ValueError):
            VoiceSettings.from_env({"TURNLAB_DEMO_FAULTS": "maybe"})

    def test_template_keys_are_not_ready(self):
        with self.assertRaisesRegex(ValueError, "GROQ_API_KEY"):
            VoiceSettings(groq_api_key="YOUR_GROQ_API_KEY", deepgram_api_key="test-only").validate_credentials()


class IntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_failed_startup_preserves_report(self):
        from turnlab import voice

        with tempfile.TemporaryDirectory(dir=ROOT / ".turnlab") as folder:
            settings = VoiceSettings(groq_api_key="test-only", deepgram_api_key="test-only", artifact_dir=Path(folder))
            callbacks = []
            context = SimpleNamespace(room=SimpleNamespace(name="fixture-room"),
                                      add_shutdown_callback=callbacks.append, connect=AsyncMock())
            with patch.object(voice.VoiceSettings, "from_env", return_value=settings):
                with patch.object(voice.silero.VAD, "load", side_effect=RuntimeError("private detail")):
                    with self.assertRaises(RuntimeError):
                        await voice.entrypoint(context)
            paths = list(Path(folder).glob("*.json"))
            self.assertEqual(len(paths), 1)
            report = ReportStore(Path(folder)).get(paths[0].stem)
            self.assertEqual(report["status"], "failed")
            self.assertEqual(report["session_events"][-1]["type"], "startup_failed")
            self.assertNotIn("private detail", str(report))
            await callbacks[0]()
            self.assertEqual(ReportStore(Path(folder)).get(paths[0].stem)["status"], "failed")

    async def test_cli_receives_local_profile_instead_of_old_cloud_environment(self):
        from turnlab import voice

        with patch.dict(os.environ, {"LIVEKIT_URL": "wss://old.invalid", "LIVEKIT_API_KEY": "old"}, clear=True):
            with patch.object(voice, "load_dotenv"), patch.object(voice.agents.cli, "run_app") as run:
                voice.main()
                self.assertEqual(os.environ["LIVEKIT_URL"], "ws://127.0.0.1:7880")
                self.assertEqual(os.environ["LIVEKIT_API_KEY"], "devkey")
                run.assert_called_once()

    async def test_reference_faults_are_opt_in_and_session_isolated(self):
        normal = ReferenceTools(ToolMonitor("normal"))
        self.assertEqual((await normal.demonstrate_booking())["status"], "disabled")
        normal_lookup = await normal.lookup_ticket("DEMO-001")
        self.assertEqual(normal_lookup["attempts"], 1)
        faulted = ReferenceTools(ToolMonitor("faulted"), inject_faults=True)
        lookup = await faulted.lookup_ticket("DEMO-001")
        self.assertEqual(lookup["attempts"], 2)
        results = await asyncio.gather(faulted.demonstrate_booking(), faulted.demonstrate_booking())
        self.assertTrue(all(result["status"] == "uncertain" for result in results))
        self.assertEqual(faulted.booking_count, 1)
        self.assertEqual(normal.booking_count, 0)
        self.assertEqual((await normal.lookup_ticket("OTHER"))["status"], "not_found")

    async def test_recorder_persists_final_report_and_bounded_events(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".turnlab") as folder:
            monitor = ToolMonitor(str(uuid4()))
            recorder = SessionRecorder(monitor, ReportStore(Path(folder)), event_limit=1)
            recorder.capture("agent_state", state="listening")
            recorder.capture("provider_error", source="STT", error_type="STTError", recoverable=False)
            recorder.start()
            await recorder.close()
            report = recorder.store.get(monitor.session_id)
            self.assertEqual(report["status"], "closed")
            self.assertFalse(report["telemetry"]["complete"])
            self.assertEqual(report["incidents"][0]["cause"], "unknown")
            self.assertFalse(report["audio_recorded"])

    async def test_persistence_failure_does_not_crash_call(self):
        monitor = ToolMonitor(str(uuid4()))
        recorder = SessionRecorder(monitor, ReportStore(Path("unused")))
        with patch.object(recorder.store, "save", side_effect=OSError("private filesystem detail")):
            await recorder.flush()
        self.assertEqual(recorder.persistence_errors, 1)
        self.assertNotIn("private filesystem detail", str(recorder.report()))

    async def test_actual_sdk_builds_direct_plugins_and_accepts_event_hooks(self):
        from livekit.agents import AgentSession
        from livekit.plugins import deepgram, groq
        from turnlab.voice import MonitoredAssistant, attach_session_events, build_session

        settings = VoiceSettings(groq_api_key="test-only", deepgram_api_key="test-only")
        # Verify actual plugin constructors and SDK event contracts without network/model calls.
        session = build_session(settings, vad=SimpleNamespace())
        self.assertIsInstance(session, AgentSession)
        self.assertIsInstance(session.stt, deepgram.STT)
        self.assertIsInstance(session.tts, deepgram.TTS)
        self.assertIsInstance(session.llm, groq.LLM)
        monitor = ToolMonitor(str(uuid4()))
        recorder = SessionRecorder(monitor, ReportStore(Path("unused")))
        attach_session_events(session, recorder)
        session.emit("agent_state_changed", SimpleNamespace(new_state="listening"))
        session.emit("error", SimpleNamespace(error=SimpleNamespace(recoverable=True), source=session.stt))
        self.assertEqual(recorder.report()["session_events"][0]["state"], "listening")
        self.assertEqual(recorder.report()["incidents"][0]["kind"], "provider_error")
        from livekit.agents.llm import ChatMessage
        from livekit.agents.voice.events import AgentFalseInterruptionEvent, ConversationItemAddedEvent
        session.emit("conversation_item_added", ConversationItemAddedEvent(item=ChatMessage(
            role="user", content=["my card number is private"], metrics={"transcription_delay": .2, "end_of_turn_delay": .4})))
        session.emit("conversation_item_added", ConversationItemAddedEvent(item=ChatMessage(
            role="assistant", content=["private reply"], interrupted=True,
            metrics={"e2e_latency": 2.5, "llm_node_ttft": 1.9, "tts_node_ttfb": .3})))
        session.emit("agent_false_interruption", AgentFalseInterruptionEvent(resumed=True))
        report = recorder.report()
        reply = next(e for e in report["session_events"] if e["type"] == "agent_reply")
        self.assertEqual((reply["wait_ms"], reply["llm_ms"], reply["tts_ms"], reply["interrupted"]), (2500, 1900, 300, True))
        self.assertEqual(next(e for e in report["session_events"] if e["type"] == "caller_turn")["stt_ms"], 200)
        self.assertEqual(report["incidents"][-1]["kind"], "slow_response")
        self.assertNotIn("private", json.dumps(report))
        assistant = MonitoredAssistant(ReferenceTools(monitor))
        self.assertEqual(len(assistant.tools), 2)
        await session.llm.aclose()
        await session.stt.aclose()
        await session.tts.aclose()
