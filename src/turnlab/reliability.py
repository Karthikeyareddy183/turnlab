"""Read-only readiness and repeatable offline acceptance demonstration."""

import importlib.util
import platform
from pathlib import Path
import sys

from turnlab.regression import run_suite, compare_runs
from turnlab.storage import ReportStore


def doctor(root: Path) -> dict:
    store = ReportStore(root / '.turnlab' / 'runs')
    records, skipped = store.catalog()
    temporary = list(store.root.glob('*.tmp')) if store.root.exists() else []
    return {"python": platform.python_version(), "python_supported": sys.version_info >= (3, 11),
            "platform": platform.system(), "dashboard_built": (root / 'web/dist/index.html').is_file(),
            "modules": {name: importlib.util.find_spec(name) is not None for name in ('fastapi', 'uvicorn', 'dotenv')},
            "reports_checked": len(records), "unreadable_reports": skipped,
            "stale_active_reports": sum(r['stale'] for r in records), "orphan_temporary_files": len(temporary),
            "notes": ["Read-only; no provider requests or report deletion.",
                      "Orphan temporary files are ignored. The last atomically saved JSON remains authoritative.",
                      "Microphone and hosted persistence acceptance are separate checks."]}


def pilot_demo(output: Path) -> dict:
    store = ReportStore(output)
    broken = [run_suite('fault_memory'), run_suite('fault_duplicate_booking')]
    fixed = run_suite('corrected')
    for report in [*broken, fixed]:
        store.save(report)
    comparisons = [compare_runs(report, fixed) for report in broken]
    return {"verified": all(r['fixes'] > 0 and r['remaining_failures'] == 0 for r in comparisons),
            "sample_size": 3, "cases_per_run": fixed['case_count'], "checks_per_run": len(fixed['checks']),
            "broken_run_ids": [r['id'] for r in broken], "corrected_run_id": fixed['id'], "comparisons": comparisons,
            "coverage": "Fresh executions of deliberately broken and corrected deterministic reference code. No LLM, microphone, speech provider, or production-scale claim."}
