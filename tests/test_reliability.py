import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from turnlab.monitoring import ToolMonitor
from turnlab.recording import SessionRecorder
from turnlab.regression import run_suite
from turnlab.storage import ReportStore
from turnlab.reliability import doctor


class ReliabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_disk_failure_does_not_kill_recording_and_can_recover(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ReportStore(Path(folder))
            recorder = SessionRecorder(ToolMonitor(run_suite()['id']), store)
            with patch.object(store, 'save', side_effect=OSError('private-path-not-logged')):
                await recorder.flush()
            self.assertEqual(recorder.persistence_errors, 1)
            await recorder.close()
            saved = store.get(recorder.monitor.session_id)
            self.assertEqual(saved['status'], 'closed')
            self.assertEqual(saved['telemetry']['persistence_errors'], 1)

    async def test_interrupted_atomic_replace_preserves_last_good_report(self):
        with tempfile.TemporaryDirectory() as folder:
            store = ReportStore(Path(folder))
            report = run_suite()
            store.save(report)
            changed = {**report, 'status': 'changed'}
            with patch('turnlab.storage.os.replace', side_effect=OSError('disk-failure')):
                with self.assertRaises(OSError):
                    store.save(changed)
            self.assertEqual(store.get(report['id']), report)
            self.assertFalse(list(Path(folder).glob('*.tmp')))

    async def test_corrupt_partial_and_oversize_artifacts_are_visible_but_not_served(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = ReportStore(root / '.turnlab/runs')
            report = run_suite()
            path = store.save(report)
            path.write_text('{', encoding='utf-8')
            (store.root / 'interrupted.tmp').write_text('partial', encoding='utf-8')
            self.assertEqual(store.summaries()['skipped_reports'], 1)
            result = doctor(root)
            self.assertEqual(result['orphan_temporary_files'], 1)
            self.assertEqual(result['unreadable_reports'], 1)
            path.write_text(json.dumps(report), encoding='utf-8')
            with patch.object(store, 'MAX_BYTES', 10):
                self.assertEqual(store.summaries()['skipped_reports'], 1)
                with self.assertRaises(ValueError):
                    store.get(report['id'])
