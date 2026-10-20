from pathlib import Path
import unittest
from uuid import uuid4

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from turnlab import telemetry
from turnlab.analysis import analyze_report
from turnlab.monitoring import ReplaySafety, ToolMonitor, ToolPolicy
from turnlab.recording import SessionRecorder
from turnlab.settings import VoiceSettings
from turnlab.storage import ReportStore


def recorder(**options):
    return SessionRecorder(ToolMonitor(str(uuid4())), ReportStore(Path("unused")), **options)


class ReplyTimingTests(unittest.IsolatedAsyncioTestCase):
    async def test_recorder_accepts_only_bounded_timings(self):
        session = recorder()
        with self.assertRaises(ValueError):
            session.capture("agent_reply", transcript="hello")
        for bad in (-1, float("inf"), "12"):
            with self.assertRaises(ValueError):
                session.capture("agent_reply", wait_ms=bad)
        session.capture("agent_reply", wait_ms=1234.567, llm_ms=None)
        self.assertEqual(session.events[-1]["wait_ms"], 1234.6)
        self.assertNotIn("llm_ms", session.events[-1])

    async def test_slow_replies_become_one_incident_with_the_worst_as_evidence(self):
        session = recorder(slow_reply_ms=1500)
        for wait in (900, 1600, 3100, 1200):
            session.capture("agent_reply", wait_ms=wait, llm_ms=wait * .8, tts_ms=wait * .1)
        report = session.report()
        slow = [i for i in report["incidents"] if i["kind"] == "slow_response"]
        self.assertEqual(len(slow), 1)
        self.assertIn("2 of 4 replies", slow[0]["observed"])
        self.assertEqual(slow[0]["evidence_event_id"], session.events[2]["id"])
        finding = analyze_report(report)["findings"][0]
        self.assertEqual(finding["title"], "Slow replies")
        self.assertIn("AI model", finding["suggestion"])
        self.assertFalse([i for i in recorder(slow_reply_ms=5000).report()["incidents"]])

    async def test_call_summary_reports_wait_percentiles_and_interruptions(self):
        session = recorder()
        for wait in (500, 700, 900, 1100, 4000):
            session.capture("agent_reply", wait_ms=wait, interrupted=wait == 4000)
        session.capture("agent_reply")  # A reply without timing is counted but not measured.
        session.capture("false_interruption", resumed=True)
        summary = analyze_report(session.report())["call_summary"]
        self.assertEqual((summary["wait_p50_ms"], summary["wait_p95_ms"], summary["wait_max_ms"]), (900, 4000, 4000))
        self.assertEqual((len(summary["replies"]), summary["interruptions"], summary["false_interruptions"]), (6, 1, 1))
        self.assertEqual(summary["slow_reply_ms"], 2000)

    def test_settings_validate_threshold_and_export_endpoint(self):
        settings = VoiceSettings.from_env({"TURNLAB_SLOW_REPLY_MS": "1200", "TURNLAB_OTEL_ENDPOINT": "https://otel.example/v1/traces"})
        self.assertEqual((settings.slow_reply_ms, settings.otel_include_conversation), (1200, False))
        for env in ({"TURNLAB_SLOW_REPLY_MS": "fast"}, {"TURNLAB_SLOW_REPLY_MS": "0"},
                    {"TURNLAB_OTEL_ENDPOINT": "https://user:key@otel.example"}, {"TURNLAB_OTEL_ENDPOINT": "ftp://otel.example"},
                    {"TURNLAB_OTEL_INCLUDE_CONVERSATION": "yes"}):
            with self.assertRaises(ValueError):
                VoiceSettings.from_env(env)


class TracingTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_attempts_and_retry_decisions_annotate_the_active_span(self):
        exporter = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        monitor = ToolMonitor(str(uuid4()))
        calls = 0

        async def flaky(context):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ConnectionError("secret detail")
            return {"ok": True}

        with provider.get_tracer("test").start_as_current_span("function_tool"):
            await monitor.execute(ToolPolicy("lookup", ReplaySafety.READ_ONLY, max_retries=1), flaky)
        events = exporter.get_finished_spans()[0].events
        decisions = [e.attributes.get("turnlab.decision") for e in events if "turnlab.decision" in e.attributes]
        self.assertEqual(decisions, ["retry"])
        self.assertEqual([e.attributes["turnlab.type"] for e in events if "turnlab.type" in e.attributes],
                         ["tool_started", "tool_error", "tool_started", "tool_succeeded"])
        self.assertNotIn("secret", str([dict(e.attributes) for e in events]))

    async def test_annotation_is_a_noop_without_an_active_span(self):
        await ToolMonitor(str(uuid4())).execute(ToolPolicy("lookup"), lambda context: _ok())

    def test_export_is_disabled_without_endpoint_and_installed_once(self):
        self.assertIsNone(telemetry.configure_tracing(""))
        exporter = InMemorySpanExporter()
        try:
            first = telemetry.configure_tracing("", exporter=exporter)
            self.assertIs(telemetry.configure_tracing("https://ignored.example", exporter=exporter), first)
            telemetry.flush_tracing()
        finally:
            telemetry._provider = None


async def _ok():
    return True
