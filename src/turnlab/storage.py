"""Atomic local artifacts; local reports remain authoritative during cloud outages."""

import json
import os
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from uuid import UUID


class ReportStore:
    MAX_BYTES = 8 * 1024 * 1024
    def __init__(self, root: Path):
        self.root = root
        # Parsed reports keyed by file name and (mtime_ns, size, inode); the live feed polls every second.
        self._cache: dict[str, tuple[tuple[int, int, int], dict[str, Any], str]] = {}

    def _path(self, run_id: str) -> Path:
        if str(UUID(run_id)) != run_id:
            raise ValueError("run id must be a canonical UUID")
        return self.root / f"{run_id}.json"

    def save(self, report: dict[str, Any]) -> Path:
        target = self._path(report["id"])
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.root, suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(report, stream, indent=2, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return target

    def get(self, run_id: str) -> dict[str, Any]:
        path = self._path(run_id)
        with path.open('rb') as stream:
            raw = stream.read(self.MAX_BYTES + 1)
        if len(raw) > self.MAX_BYTES:
            raise ValueError("artifact exceeds the size limit")
        report = json.loads(raw)
        if not isinstance(report, dict) or report.get('id') != run_id:
            raise ValueError("invalid artifact identity")
        return report

    def catalog(self, limit: int = 100) -> tuple[list[dict[str, Any]], int]:
        """Read consistent atomic snapshots; malformed reports are counted, not served."""
        if not self.root.exists():
            return [], 0
        records, skipped = [], 0
        candidates = []
        for path in self.root.glob("*.json"):
            try:
                candidates.append((path.stat().st_mtime_ns, path))
            except OSError:
                skipped += 1
        paths = [path for _, path in sorted(candidates, reverse=True)]
        cache = {}
        for path in paths[:limit]:
            try:
                self._path(path.stem)
                before = path.stat()
                version = (before.st_mtime_ns, before.st_size, before.st_ino)
                cached = self._cache.get(path.name)
                if cached and cached[0] == version:
                    cache[path.name] = cached
                    records.append(self._record(cached[1], cached[2], before.st_mtime))
                    continue
                if before.st_size > self.MAX_BYTES:
                    raise ValueError("artifact exceeds the size limit")
                with path.open('rb') as stream:
                    raw = stream.read(self.MAX_BYTES + 1)
                if len(raw) > self.MAX_BYTES:
                    raise ValueError("artifact exceeds the size limit")
                after = path.stat()
                if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
                    skipped += 1
                    continue
                report = json.loads(raw)
                if not isinstance(report, dict) or report.get("id") != path.stem:
                    raise ValueError("invalid report identity")
                if any(not isinstance(report.get(key), str) for key in ("created_at", "mode", "status")):
                    raise ValueError("missing report fields")
                for key in ("incidents", "checks", "events", "session_events"):
                    if key in report and (not isinstance(report[key], list) or any(not isinstance(item, dict) for item in report[key])):
                        raise ValueError("invalid report collections")
                fingerprint = sha256(raw).hexdigest()
                cache[path.name] = ((after.st_mtime_ns, after.st_size, after.st_ino), report, fingerprint)
                records.append(self._record(report, fingerprint, after.st_mtime))
            except (ValueError, OSError):
                skipped += 1
        self._cache = cache
        return records, skipped

    @staticmethod
    def _record(report: dict[str, Any], fingerprint: str, mtime: float) -> dict[str, Any]:
        return {"report": report, "fingerprint": fingerprint,
                "updated_at": datetime.fromtimestamp(mtime, timezone.utc).isoformat(),
                "stale": report.get("status") == "active" and datetime.now(timezone.utc).timestamp() - mtime > 15}

    def summaries(self) -> dict[str, Any]:
        records, skipped = self.catalog()
        runs = []
        for record in records:
            report = record["report"]
            checks = report.get("checks", [])
            incidents = report.get("incidents", [])
            recovered = sum(i.get("recovery_outcome") == "recovered" for i in incidents)
            runs.append({"id": report["id"], "title": report.get("scenario_name") or report.get("room_name") or "Tool recovery demonstration",
                         "mode": report.get("mode", "unknown"), "status": report.get("status", "unknown"),
                         "created_at": report.get("created_at"), "updated_at": record["updated_at"], "stale": record["stale"],
                         "incident_count": len(incidents),
                         "failed_check_count": sum(c.get("passed") is False for c in checks),
                         "recovered_count": recovered,
                         "needs_review_count": len(incidents) - recovered + sum(c.get("passed") is False for c in checks),
                         "fingerprint": record["fingerprint"]})
        return {"runs": runs, "skipped_reports": skipped, "limit": 100}

