import asyncio
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from uuid import uuid4

from turnlab.analysis import analyze_report
from turnlab.core import Scenario, grade
from turnlab.monitoring import run_monitor_demo
from turnlab.storage import ReportStore
from turnlab.streaming import stream_reports
from turnlab.synchronization import SupabaseSync, SyncSettings, metadata_row

ROOT = Path(__file__).resolve().parents[1]


def setUpModule():
    (ROOT / ".turnlab").mkdir(exist_ok=True)


class DashboardTests(unittest.IsolatedAsyncioTestCase):
    async def test_catalog_and_analysis_do_not_claim_a_root_cause(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".turnlab") as folder:
            store = ReportStore(Path(folder))
            report = await run_monitor_demo()
            path = store.save(report)
            catalog = store.summaries()
            self.assertEqual(catalog["runs"][0]["incident_count"], 2)
            analysis = analyze_report(report)
            self.assertTrue(all(f["cause_status"] == "not_established" and f["cause"] is None for f in analysis["findings"]))
            self.assertTrue(all(f["evidence_available"] for f in analysis["findings"]))
            report["events"] = []
            self.assertFalse(analyze_report(report)["findings"][0]["evidence_available"])
            report["status"] = "active"
            store.save(report)
            os.utime(path, (1, 1))
            self.assertTrue(store.summaries()["runs"][0]["stale"])

    async def test_invalid_reports_are_visible_as_skipped(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".turnlab") as folder:
            store = ReportStore(Path(folder))
            (store.root / f"{uuid4()}.json").write_text("{broken")
            (store.root / "not-a-uuid.json").write_text("{}")
            self.assertEqual(store.summaries()["skipped_reports"], 2)

    async def test_stream_snapshots_and_reconnection(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".turnlab") as folder:
            store = ReportStore(Path(folder))
            async def connected():
                return False
            stream = stream_reports(store, connected, interval=.001)
            first = await anext(stream)
            self.assertIn('"runs": []', first)
            store.save(await run_monitor_demo())
            update = await asyncio.wait_for(anext(stream), timeout=2)
            self.assertIn('"incident_count": 2', update)
            await stream.aclose()
            reconnect = stream_reports(store, connected)
            self.assertIn('"incident_count": 2', await anext(reconnect))
            await reconnect.aclose()

    async def test_api_catalog_analysis_exports_and_origin_boundary(self):
        from httpx import ASGITransport, AsyncClient
        from turnlab.api import create_app
        with tempfile.TemporaryDirectory(dir=ROOT / ".turnlab") as folder:
            async with AsyncClient(transport=ASGITransport(app=create_app(ROOT / "scenarios", Path(folder))), base_url="http://test") as client:
                result = await client.post("/api/demos/tool-monitor")
                run_id = result.json()["id"]
                self.assertEqual(len((await client.get("/api/runs")).json()["runs"]), 1)
                self.assertEqual(len((await client.get(f"/api/runs/{run_id}/analysis")).json()["findings"]), 2)
                exported = await client.get(f"/api/runs/{run_id}/export")
                self.assertIn("attachment", exported.headers["content-disposition"])
                self.assertEqual(exported.json()["id"], run_id)
                denied = await client.post("/api/demos/tool-monitor", headers={"Origin": "https://untrusted.invalid"})
                self.assertEqual(denied.status_code, 403)
                self.assertEqual((await client.get("/api/runs", headers={"Host": "untrusted.invalid"})).status_code, 400)
                self.assertEqual((await client.get("/api/health")).json()["synchronization"]["state"], "disabled")

    async def test_finding_titles_come_from_any_tool_name(self):
        report = {"id": str(uuid4()), "incidents": [
            {"id": "1", "kind": "tool_timeout", "tool": "create_invoice"},
            {"id": "2", "kind": "tool_error", "tool": "fetch-crm-record"},
            {"id": "3", "kind": "provider_error", "source": "STT"}]}
        titles = [f["title"] for f in analyze_report(report)["findings"]]
        self.assertEqual(titles, ["Create invoice timed out", "Fetch crm record failed", "Voice service error (STT)"])

    async def test_call_summary_counts_turns_and_agent_states(self):
        session = [("agent_state", "listening", 0), ("user_state", "speaking", 100), ("agent_state", "thinking", 900),
                   ("agent_state", "speaking", 2100), ("user_state", "speaking", 4000), ("agent_state", "thinking", 4500),
                   ("agent_state", "speaking", 5000), ("provider_error", None, 5200), ("agent_state", "listening", 6000)]
        report = {"id": str(uuid4()), "mode": "livekit_session", "retries_used": 1,
                  "session_events": [{"id": str(i), "type": t, "offset_ms": o, **({"state": s} if s else {})} for i, (t, s, o) in enumerate(session)],
                  "events": [{"id": "t1", "type": "tool_started", "attempt": 1, "offset_ms": 1000},
                             {"id": "t2", "type": "tool_started", "attempt": 2, "offset_ms": 1500}]}
        summary = analyze_report(report)["call_summary"]
        self.assertEqual((summary["duration_ms"], summary["caller_turns"], summary["agent_turns"]), (6000, 2, 2))
        self.assertEqual((summary["tool_calls"], summary["retries"], summary["provider_errors"]), (1, 1, 1))
        self.assertEqual(summary["longest_thinking_ms"], 1200)
        self.assertEqual([s["state"] for s in summary["agent_states"]], ["listening", "thinking", "speaking", "thinking", "speaking", "listening"])
        self.assertIsNone(analyze_report({**report, "mode": "fixture"})["call_summary"])

    async def test_summaries_split_recovered_from_needs_review_and_refresh_cache(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".turnlab") as folder:
            store = ReportStore(Path(folder))
            report = await run_monitor_demo()
            store.save(report)
            run = store.summaries()["runs"][0]
            self.assertEqual((run["recovered_count"], run["needs_review_count"]), (1, 1))
            self.assertEqual(store.summaries()["runs"][0]["fingerprint"], run["fingerprint"])
            report["incidents"] = report["incidents"][:1]
            store.save(report)
            changed = store.summaries()["runs"][0]
            self.assertEqual((changed["recovered_count"], changed["needs_review_count"]), (1, 0))
            self.assertNotEqual(changed["fingerprint"], run["fingerprint"])

    async def test_failed_assertion_is_an_observation_not_diagnosis(self):
        report = grade(Scenario.load(ROOT / "scenarios/memory-leak.json"))
        finding = analyze_report(report)["findings"][0]
        self.assertEqual(finding["kind"], "assertion_failed")
        self.assertEqual(finding["cause_status"], "not_established")

    async def test_metadata_redaction_and_idempotent_sync_receipts(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".turnlab") as folder:
            store = ReportStore(Path(folder) / "runs")
            report = await run_monitor_demo()
            report["events"][0]["private"] = "secret-personal-data"
            report["telemetry"]["raw_error"] = "secret-personal-data"
            store.save(report)
            settings = SyncSettings("https://example.supabase.co", "sb_secret_test_only")
            sync = SupabaseSync(store, settings)
            row = metadata_row(store.catalog()[0][0], "local")
            self.assertNotIn("secret-personal-data", json.dumps(row))
            self.assertNotIn("events", row)
            with patch.object(sync, "_push") as push:
                sync.sync_once()
                self.assertEqual(sync.state, "synced")
                sync.sync_once()
                self.assertEqual(push.call_count, 1)
                report["status"] = "closed"
                store.save(report)
                sync.sync_once()
                self.assertEqual(push.call_count, 2)

    async def test_sync_outage_preserves_local_report_and_retries(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".turnlab") as folder:
            store = ReportStore(Path(folder) / "runs")
            report = await run_monitor_demo()
            store.save(report)
            sync = SupabaseSync(store, SyncSettings("https://example.supabase.co", "sb_secret_test_only"))
            with patch.object(sync, "_push", side_effect=HTTPError("private-url", 401, "secret-body", {}, None)):
                sync.sync_once()
            self.assertEqual(sync.state, "error")
            self.assertNotIn("secret-body", sync.last_error)
            self.assertEqual(store.get(report["id"])["id"], report["id"])
            with patch.object(sync, "_push") as push:
                sync.sync_once()
                push.assert_called_once()

    async def test_sync_config_has_no_implicit_cloud_mode(self):
        self.assertIsNone(SyncSettings.from_env({}))
        with self.assertRaises(ValueError):
            SyncSettings.from_env({"SUPABASE_URL": "https://example.supabase.co", "SUPABASE_SECRET_KEY": "sb_publishable_wrong"})
        self.assertNotIn("sb_secret_test_only", repr(SyncSettings("https://example.supabase.co", "sb_secret_test_only")))
