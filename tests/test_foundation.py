import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from turnlab.core import ContractError, Scenario, grade
from turnlab.storage import ReportStore

ROOT = Path(__file__).resolve().parents[1]


def setUpModule():
    (ROOT / ".turnlab").mkdir(exist_ok=True)


class FoundationTests(unittest.TestCase):
    def load(self, name="booking-correct"):
        return Scenario.load(ROOT / "scenarios" / f"{name}.json")

    def test_clean_fixture_passes_without_claiming_audio_metrics(self):
        report = grade(self.load())
        self.assertEqual(report["status"], "passed")
        self.assertTrue(all(m["status"] == "not_measured" for m in report["metrics"].values()))

    def test_state_assertion_catches_duplicate_effect_not_just_retries(self):
        scenario = self.load("duplicate-booking")
        self.assertEqual(grade(scenario)["status"], "failed")
        scenario.final_state["booking_count"] = 1
        self.assertEqual(grade(scenario)["status"], "passed")

    def test_out_of_scope_read_has_event_evidence(self):
        report = grade(self.load("memory-leak"))
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["checks"][0]["event_indexes"], [0])

    def test_wrong_tool_arguments_fail_even_if_state_claims_success(self):
        scenario = self.load()
        scenario.events[1]["data"]["arguments"]["day"] = "Thursday"
        report = grade(scenario)
        self.assertFalse(report["checks"][0]["passed"])
        self.assertTrue(report["checks"][1]["passed"])

    def test_missing_state_key_is_not_equal_to_null(self):
        raw = json.loads((ROOT / "scenarios/booking-correct.json").read_text())
        raw["assertions"] = [{"id": "missing", "kind": "state_equals", "key": "absent", "expected": None}]
        self.assertEqual(grade(Scenario.parse(raw))["status"], "failed")

    def test_invalid_contracts_rejected(self):
        original = json.loads((ROOT / "scenarios/booking-correct.json").read_text())
        mutations = [
            lambda x: x.update(mode="audio"),
            lambda x: x.update(schema_version=True),
            lambda x: x.update(assertions=[]),
            lambda x: x.update(id="../escape"),
            lambda x: x["events"][0].update(type=[]),
            lambda x: x["events"][0].update(offset_ms=float("nan")),
            lambda x: x["events"][2].update(offset_ms=1),
            lambda x: x["assertions"].append(copy.deepcopy(x["assertions"][0])),
        ]
        for mutation in mutations:
            raw = copy.deepcopy(original)
            mutation(raw)
            with self.subTest(raw=raw), self.assertRaises(ContractError):
                Scenario.parse(raw)

    def test_atomic_report_and_path_validation(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".turnlab") as folder:
            store = ReportStore(Path(folder))
            report = grade(self.load())
            store.save(report)
            self.assertEqual(store.get(report["id"]), report)
            self.assertEqual(len(list(Path(folder).iterdir())), 1)
            with self.assertRaises(ValueError):
                store.get("../escape")

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".turnlab") as folder:
            for scenario, expected in [("booking-correct", 0), ("duplicate-booking", 1), ("missing", 2)]:
                result = subprocess.run([sys.executable, "-m", "turnlab", "run",
                                         str(ROOT / "scenarios" / f"{scenario}.json"), "--output", folder],
                                        capture_output=True, text=True, timeout=15)
                self.assertEqual(result.returncode, expected, result.stderr)


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_fixture_api_round_trip_and_validation(self):
        from httpx import ASGITransport, AsyncClient
        from turnlab.api import create_app

        with tempfile.TemporaryDirectory(dir=ROOT / ".turnlab") as folder:
            async with AsyncClient(transport=ASGITransport(app=create_app(ROOT / "scenarios", Path(folder))), base_url="http://test", timeout=10) as client:
                self.assertFalse((await client.get("/api/health")).json()["diagnosis_available"])
                self.assertEqual(len((await client.get("/api/scenarios")).json()), 3)
                response = await client.post("/api/runs", json={"scenario_id": "memory-leak"})
                self.assertEqual(response.status_code, 201)
                report = response.json()
                self.assertEqual(report["status"], "failed")
                self.assertEqual((await client.get(f'/api/runs/{report["id"]}')).json(), report)
                self.assertEqual((await client.post("/api/runs", json={"scenario_id": "../escape"})).status_code, 404)
                self.assertEqual((await client.post("/api/runs", json={"scenario_id": "booking-correct", "path": "secret"})).status_code, 422)
                self.assertEqual((await client.get("/api/runs/not-a-uuid")).status_code, 422)
                demo = await client.post("/api/demos/tool-monitor")
                self.assertEqual(demo.status_code, 201)
                self.assertEqual(demo.json()["mode"], "tool_fixture_execution")
                self.assertEqual(demo.json()["committed_bookings"], 1)
                self.assertEqual(demo.json()["operations"]["booking"]["status"], "uncertain")


if __name__ == "__main__":
    (ROOT / ".turnlab").mkdir(exist_ok=True)
    unittest.main()
