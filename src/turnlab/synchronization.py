"""Optional backend-only Supabase metadata replication. Local reports stay authoritative."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from turnlab.storage import ReportStore


@dataclass(frozen=True)
class SyncSettings:
    url: str
    key: str = field(repr=False)
    workspace: str = "local"

    @classmethod
    def from_env(cls, env: Mapping[str, str]):
        url, key = env.get("SUPABASE_URL", "").strip(), env.get("SUPABASE_SECRET_KEY", "").strip()
        if not url and not key:
            return None
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
            raise ValueError("SUPABASE_URL must be an HTTPS project origin")
        if not key.startswith("sb_secret_"):
            raise ValueError("SUPABASE_SECRET_KEY must be a backend secret key")
        workspace = env.get("TURNLAB_WORKSPACE", "local").strip()
        if not workspace or len(workspace) > 100:
            raise ValueError("TURNLAB_WORKSPACE must contain 1–100 characters")
        return cls(url.rstrip("/"), key, workspace)


def metadata_row(record: dict, workspace: str) -> dict:
    report = record["report"]
    # Intentionally exclude raw events, arguments/results, audio, transcripts, room names,
    # arbitrary exception text, and local filesystem paths from hosted metadata.
    incidents = [{k: item[k] for k in ("id", "kind", "tool", "attempt", "error_type", "source", "cause", "recovery", "recovery_outcome", "evidence_event_id") if k in item}
                 for item in report.get("incidents", [])]
    checks = [{k: item[k] for k in ("id", "kind", "passed") if k in item} for item in report.get("checks", [])]
    return {"workspace": workspace, "id": report["id"], "mode": report.get("mode", "unknown"),
            "status": report.get("status", "unknown"), "created_at": report["created_at"],
            "source_updated_at": record["updated_at"], "fingerprint": record["fingerprint"],
            "metadata": {"artifact_id": report["id"], "incident_count": len(incidents), "checks": checks,
                         "telemetry": {key: value for key, value in report.get("telemetry", {}).items()
                                       if key in {"complete", "dropped_events", "dropped_incidents", "session_events_dropped", "persistence_errors"}
                                       and type(value) in (int, bool)}}, "incidents": incidents}


class SupabaseSync:
    def __init__(self, store: ReportStore, settings: SyncSettings | None):
        self.store, self.settings = store, settings
        self.receipts = ReportStore(store.root.parent / "sync")
        self.state = "not_checked" if settings else "disabled"
        self.last_error: str | None = None
        self.last_success: str | None = None
        self._stop = asyncio.Event()

    def status(self):
        return {"configured": self.settings is not None, "state": self.state,
                "last_error": self.last_error, "last_success": self.last_success}

    def _push(self, row: dict) -> None:
        assert self.settings is not None
        req = Request(self.settings.url + "/rest/v1/turnlab_runs?on_conflict=workspace,id",
                      data=json.dumps(row, allow_nan=False).encode(), method="POST",
                      headers={"apikey": self.settings.key, "Content-Type": "application/json",
                               "Prefer": "resolution=merge-duplicates,return=minimal"})
        with urlopen(req, timeout=5) as response:
            response.read()

    def sync_once(self) -> None:
        if self.settings is None:
            return
        try:
            records, skipped = self.store.catalog()
            pushed = 0
            for record in records:
                report_id = record["report"]["id"]
                fingerprint = record["fingerprint"]
                try:
                    receipt = self.receipts.get(report_id)
                except (OSError, ValueError):
                    receipt = {}
                # Changing project or workspace must not reuse another destination's receipt.
                destination = self.settings.url + "/" + self.settings.workspace
                if receipt.get("fingerprint") == fingerprint and receipt.get("destination") == destination:
                    continue
                self._push(metadata_row(record, self.settings.workspace))
                pushed += 1
                self.receipts.save({"id": report_id, "fingerprint": fingerprint, "destination": destination})
            self.state = "synced" if pushed else "up_to_date" if records else "ready"
            self.last_error = f"{skipped} unreadable or changing reports skipped" if skipped else None
            if pushed:
                self.last_success = datetime.now(timezone.utc).isoformat()
        except HTTPError as exc:
            self.state, self.last_error = "error", f"Supabase returned HTTP {exc.code}; check configuration and migration."
        except (OSError, URLError, ValueError, KeyError):
            self.state, self.last_error = "error", "Metadata synchronization failed; local reports are retained."

    async def run(self) -> None:
        while not self._stop.is_set():
            await asyncio.to_thread(self.sync_once)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=5)
            except TimeoutError:
                pass

    def stop(self) -> None:
        self._stop.set()
