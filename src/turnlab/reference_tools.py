"""Session-isolated demo tools; no external bookings or customer data."""

from dataclasses import asdict

from turnlab.monitoring import ReplaySafety, ToolContext, ToolMonitor, ToolPolicy


class ReferenceTools:
    def __init__(self, monitor: ToolMonitor, *, inject_faults: bool = False):
        self.monitor = monitor
        self.inject_faults = inject_faults
        self.lookup_calls = 0
        self.booking_count = 0
        self._booking_started = False

    async def lookup_ticket(self, ticket_id: str) -> dict:
        if ticket_id != "DEMO-001":
            return {"status": "not_found", "message": "Only fixture ticket DEMO-001 exists."}

        async def lookup(context: ToolContext):
            self.lookup_calls += 1
            if self.inject_faults and self.lookup_calls == 1:
                raise ConnectionError("injected demo failure")
            return {"ticket_id": "DEMO-001", "status": "scheduled", "day": "Friday", "fixture": True}

        outcome = await self.monitor.execute(ToolPolicy("lookup_demo_ticket", ReplaySafety.READ_ONLY, max_retries=1), lookup)
        return asdict(outcome)

    async def demonstrate_booking(self) -> dict:
        if not self.inject_faults:
            return {"status": "disabled", "message": "Fault demonstrations are disabled in this profile."}
        if self._booking_started:
            return {"status": "uncertain", "message": "The earlier demo write is unresolved; do not book again.",
                    "committed_fixture_bookings": self.booking_count}

        self._booking_started = True

        async def book(context: ToolContext):
            self.booking_count += 1
            raise TimeoutError("injected acknowledgement loss")

        outcome = await self.monitor.execute(ToolPolicy("demo_booking", max_retries=2), book)
        return {**asdict(outcome), "committed_fixture_bookings": self.booking_count,
                "message": "Simulated booking outcome is uncertain. Review requested; no human transfer was made."}
