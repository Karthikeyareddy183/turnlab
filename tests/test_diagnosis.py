import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from turnlab.diagnosis import DiagnosisError, GroqDiagnoser, evidence_payload, validate_diagnosis
from turnlab.monitoring import run_monitor_demo
from turnlab.storage import ReportStore

ROOT = Path(__file__).resolve().parents[1]


def setUpModule():
    (ROOT / ".turnlab").mkdir(exist_ok=True)


class DiagnosisTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_supplied_findings_and_event_references_are_accepted(self):
        report = await run_monitor_demo()
        payload = evidence_payload(report)
        value = {"hypotheses": [{"finding_id": payload["findings"][0]["id"], "hypothesis": "A dependency may have been unavailable.",
                                  "evidence_event_ids": [payload["events"][1]["id"]], "investigation": "Check the dependency logs."}]}
        self.assertEqual(len(validate_diagnosis(json.dumps(value), payload)["hypotheses"]), 1)
        value["hypotheses"][0]["evidence_event_ids"] = ["fabricated-event"]
        with self.assertRaises(DiagnosisError):
            validate_diagnosis(json.dumps(value), payload)
        with self.assertRaises(DiagnosisError):
            validate_diagnosis("not json", payload)

    async def test_payload_omits_transcripts_arguments_and_private_error_text(self):
        report = await run_monitor_demo()
        report["transcript"] = "private-transcript"
        report["events"][0]["arguments"] = {"key": "private-secret"}
        report["incidents"][0]["error_message"] = "private-secret"
        text = json.dumps(evidence_payload(report))
        self.assertNotIn("private-secret", text)
        self.assertNotIn("private-transcript", text)

    async def test_api_persists_opt_in_diagnosis_and_marks_stale_evidence(self):
        from httpx import ASGITransport, AsyncClient
        from turnlab.api import create_app
        with tempfile.TemporaryDirectory(dir=ROOT / ".turnlab") as folder:
            store = ReportStore(Path(folder) / "runs")
            report = await run_monitor_demo()
            store.save(report)
            diagnoser = GroqDiagnoser("test-only")
            app = create_app(ROOT / "scenarios", store.root, diagnoser=diagnoser)
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                endpoint = f'/api/runs/{report["id"]}/diagnosis'
                self.assertEqual((await client.get(endpoint)).json()["state"], "not_requested")
                with patch.object(GroqDiagnoser, "diagnose", return_value={"hypotheses": [], "model": "test-model"}):
                    response = await client.post(endpoint)
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.json()["stale"])
                report["status"] = "closed"
                store.save(report)
                self.assertTrue((await client.get(endpoint)).json()["stale"])

    async def test_missing_configuration_or_provider_failure_does_not_invent_diagnosis(self):
        from httpx import ASGITransport, AsyncClient
        from turnlab.api import create_app
        with tempfile.TemporaryDirectory(dir=ROOT / ".turnlab") as folder:
            report = await run_monitor_demo()
            store = ReportStore(Path(folder) / "runs")
            store.save(report)
            endpoint = f'/api/runs/{report["id"]}/diagnosis'
            for diagnoser, expected in ((None, 503), (GroqDiagnoser("test-only"), 502)):
                async with AsyncClient(transport=ASGITransport(app=create_app(ROOT / "scenarios", store.root, diagnoser=diagnoser)), base_url="http://test") as client:
                    with patch.object(GroqDiagnoser, "diagnose", side_effect=DiagnosisError("Diagnosis unavailable")):
                        self.assertEqual((await client.post(endpoint)).status_code, expected)
