import asyncio
import unittest

from turnlab.monitoring import ReplaySafety, ToolMonitor, ToolPolicy, run_monitor_demo


class MonitoringTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_retry_recovers_and_preserves_evidence(self):
        report = await run_monitor_demo()
        self.assertEqual(report["operations"]["lookup"]["status"], "succeeded")
        self.assertEqual(report["operations"]["lookup"]["attempts"], 2)
        self.assertEqual(report["incidents"][0]["recovery_outcome"], "recovered")
        event_ids = {e["id"] for e in report["events"]}
        self.assertTrue(all(i["evidence_event_id"] in event_ids for i in report["incidents"]))

    async def test_unknown_write_outcome_never_blindly_retries(self):
        report = await run_monitor_demo()
        self.assertEqual(report["operations"]["booking"]["status"], "uncertain")
        self.assertEqual(report["operations"]["booking"]["attempts"], 1)
        self.assertEqual(report["committed_bookings"], 1)
        self.assertEqual(report["incidents"][-1]["recovery"], "request_human_review")

    async def test_idempotent_write_reuses_key_and_operation_id(self):
        monitor = ToolMonitor("session")
        contexts = []
        committed = set()

        async def operation(context):
            contexts.append(context)
            committed.add(context.idempotency_key)
            if context.attempt == 1:
                raise TimeoutError()
            return "ok"

        result = await monitor.execute(ToolPolicy("write", ReplaySafety.IDEMPOTENT_WRITE, max_retries=1),
                                       operation, idempotency_key="booking-1")
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(len(committed), 1)
        self.assertEqual(contexts[0].operation_id, contexts[1].operation_id)
        self.assertEqual(contexts[0].idempotency_key, contexts[1].idempotency_key)

    async def test_idempotent_declaration_without_key_cannot_retry(self):
        async def operation(context):
            raise TimeoutError()
        result = await ToolMonitor("session").execute(
            ToolPolicy("write", ReplaySafety.IDEMPOTENT_WRITE, max_retries=2), operation)
        self.assertEqual(result.status, "uncertain")
        self.assertEqual(result.attempts, 1)

    async def test_write_connection_loss_is_also_uncertain(self):
        async def operation(context):
            raise ConnectionError()
        result = await ToolMonitor("session").execute(ToolPolicy("write", max_retries=2), operation)
        self.assertEqual(result.status, "uncertain")
        self.assertEqual(result.attempts, 1)

    async def test_retry_budget_shared_across_operations(self):
        monitor = ToolMonitor("session", max_call_retries=1)

        async def operation(context):
            raise ConnectionError("secret api-key must not be captured")

        policy = ToolPolicy("read", ReplaySafety.READ_ONLY, max_retries=3)
        first = await monitor.execute(policy, operation)
        second = await monitor.execute(policy, operation)
        self.assertEqual((first.attempts, second.attempts), (2, 1))
        self.assertEqual(monitor.retries_used, 1)
        self.assertNotIn("secret", str(monitor.snapshot()))

    async def test_non_transient_error_does_not_retry(self):
        async def operation(context):
            raise ValueError("bad arguments")
        result = await ToolMonitor("session").execute(
            ToolPolicy("read", ReplaySafety.READ_ONLY, max_retries=3), operation)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(result.status, "failed")

    async def test_actual_deadline_and_cancellation(self):
        cancelled = asyncio.Event()

        async def slow(context):
            try:
                await asyncio.sleep(10)
            finally:
                cancelled.set()

        monitor = ToolMonitor("session")
        result = await monitor.execute(ToolPolicy("slow", timeout_seconds=0.01), slow)
        self.assertEqual(result.status, "uncertain")
        self.assertTrue(cancelled.is_set())
        self.assertEqual(monitor.snapshot()["incidents"][0]["cause"], "unknown")

    async def test_caller_cancellation_propagates_without_retry(self):
        started = asyncio.Event()

        async def operation(context):
            started.set()
            await asyncio.sleep(10)

        monitor = ToolMonitor("session")
        task = asyncio.create_task(monitor.execute(ToolPolicy("read", ReplaySafety.READ_ONLY, max_retries=3), operation))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(monitor.retries_used, 0)
        self.assertEqual(monitor.snapshot()["events"][-1]["type"], "tool_cancelled")

    async def test_evidence_is_bounded_and_gaps_are_visible(self):
        monitor = ToolMonitor("session", evidence_limit=1)

        async def operation(context):
            return 1

        await monitor.execute(ToolPolicy("read"), operation)
        snapshot = monitor.snapshot()
        self.assertEqual(len(snapshot["events"]), 1)
        self.assertEqual(snapshot["telemetry"]["dropped_events"], 1)
        self.assertFalse(snapshot["telemetry"]["complete"])
        snapshot["events"][0]["type"] = "tampered"
        self.assertNotEqual(monitor.snapshot()["events"][0]["type"], "tampered")

    async def test_invalid_policy_rejected(self):
        for values in ({"timeout_seconds": 0}, {"timeout_seconds": float("nan")},
                       {"max_retries": -1}, {"max_retries": True}, {"replay_safety": "read_only"}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                ToolPolicy("tool", **values)
