import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import wave

from turnlab.audio import score_transcript, transcribe_wav
from turnlab.memory import ScopedMemory
from turnlab.regression import run_suite, compare_runs, incident_draft
from turnlab.reliability import pilot_demo

ROOT = Path(__file__).resolve().parents[1]


class MemoryTests(unittest.TestCase):
    def test_correction_scope_expiry_and_delete(self):
        now = [0]
        memory = ScopedMemory(clock=lambda: now[0])
        first = memory.put('a', 'u', 'day', 'Thursday', ttl=10)
        corrected = memory.put('a', 'u', 'day', 'Friday', ttl=10)
        self.assertGreater(corrected.version, first.version)
        self.assertEqual(memory.get('a', 'u', 'day').value, 'Friday')
        self.assertIsNone(memory.get('a', 'v', 'day'))
        self.assertIsNone(memory.get('b', 'u', 'day'))
        now[0] = 10
        self.assertIsNone(memory.get('a', 'u', 'day'))
        memory.put('a', 'u', 'day', 'Monday')
        self.assertTrue(memory.forget('a', 'u', 'day'))
        self.assertIsNone(memory.get('a', 'u', 'day'))

    def test_bounded_memory_and_invalid_ttl(self):
        memory = ScopedMemory(capacity=1)
        memory.put('a', 'u', 'one', '1')
        memory.put('a', 'u', 'two', '2')
        self.assertIsNone(memory.get('a', 'u', 'one'))
        for ttl in (0, -1, True, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                memory.put('a', 'u', 'key', 'value', ttl=ttl)


class RegressionTests(unittest.TestCase):
    def test_actual_execution_catches_faults_and_corrected_controller_passes(self):
        fixed = run_suite()
        self.assertEqual(fixed['status'], 'passed')
        self.assertEqual(len(fixed['checks']), 8)
        for profile in ('fault_memory', 'fault_duplicate_booking'):
            broken = run_suite(profile)
            self.assertEqual(broken['status'], 'failed')
            result = compare_runs(broken, fixed)
            self.assertGreater(result['fixes'], 0)
            self.assertEqual(result['remaining_failures'], 0)
            self.assertGreater(compare_runs(fixed, broken)['regressions'], 0)
        with self.assertRaises(ValueError):
            run_suite('arbitrary-code')

    def test_comparison_rejects_contract_and_coverage_changes(self):
        baseline = run_suite()
        for mutation in (lambda r: r.update(mode='fixture'), lambda r: r.update(contract_fingerprint='other'),
                         lambda r: r['checks'].pop(), lambda r: r['checks'].append(r['checks'][0]),
                         lambda r: r['checks'][0].update(expected='changed')):
            candidate = copy.deepcopy(baseline)
            mutation(candidate)
            with self.assertRaises(ValueError):
                compare_runs(baseline, candidate)

    def test_incident_conversion_is_review_required_without_guessed_expectations(self):
        draft = incident_draft(run_suite('fault_memory'))
        self.assertEqual(draft['review_status'], 'required')
        self.assertTrue(draft['source_failed_checks'])
        self.assertIsNone(draft['expected_outcome'])
        self.assertEqual(draft['reproduction_steps'], [])

    def test_pilot_creates_fresh_artifacts(self):
        with tempfile.TemporaryDirectory() as folder:
            result = pilot_demo(Path(folder))
            self.assertTrue(result['verified'])
            self.assertEqual(len(list(Path(folder).glob('*.json'))), 3)


class AudioTests(unittest.TestCase):
    def test_recorded_wav_validation_and_provider_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.wav'
            path.write_bytes(b'not-a-wave')
            with self.assertRaises(ValueError):
                transcribe_wav(path, 'dummy')
            with wave.open(str(path), 'wb') as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(16000)
                audio.writeframes(b'\x00\x00' * 1600)
            response = MagicMock()
            response.__enter__.return_value.read.return_value = b'{"results":{"channels":[{"alternatives":[{"transcript":"book friday"}]}]}}'
            with patch('turnlab.audio.urlopen', return_value=response) as request:
                self.assertEqual(transcribe_wav(path, 'dummy'), 'book friday')
                self.assertEqual(request.call_args.args[0].get_method(), 'POST')
                self.assertEqual(request.call_args.args[0].get_header('Content-type'), 'audio/wav')
            with patch('turnlab.audio.urlopen', side_effect=OSError('private-provider-body')):
                with self.assertRaisesRegex(ValueError, '^Deepgram transcription failed') as error:
                    transcribe_wav(path, 'dummy')
                self.assertNotIn('private-provider-body', str(error.exception))

    def test_counts_normalization_empty_and_insertions_above_one(self):
        report = score_transcript('Book FRIDAY!', 'book friday')
        self.assertEqual(report['metrics']['wer']['value'], 0)
        report = score_transcript('book a visit', 'book the visit now')
        self.assertEqual((report['substitutions'], report['deletions'], report['insertions']), (1, 0, 1))
        self.assertAlmostEqual(report['metrics']['wer']['value'], 2 / 3)
        self.assertEqual(score_transcript('a b', '')['deletions'], 2)
        self.assertGreater(score_transcript('a', 'a b c')['metrics']['wer']['value'], 1)
        self.assertEqual(score_transcript('ＦＲＩＤＡＹ', 'friday')['metrics']['wer']['value'], 0)
        for reference, hypothesis in [('...', 'text'), ('a ' * 2001, 'a')]:
            with self.assertRaises(ValueError):
                score_transcript(reference, hypothesis)
        with self.assertRaises(ValueError):
            score_transcript('test', 'test', language='unknown')


class RegressionApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_execute_compare_draft_and_score_routes(self):
        from httpx import ASGITransport, AsyncClient
        from turnlab.api import create_app
        with tempfile.TemporaryDirectory() as folder:
            async with AsyncClient(transport=ASGITransport(app=create_app(ROOT / 'scenarios', Path(folder) / 'runs')), base_url='http://test') as client:
                broken = (await client.post('/api/regressions/run', json={'profile': 'fault_memory'})).json()
                fixed = (await client.post('/api/regressions/run', json={})).json()
                comparison = await client.post('/api/regressions/compare', json={'baseline_id': broken['id'], 'candidate_id': fixed['id']})
                self.assertEqual(comparison.status_code, 200)
                self.assertGreater(comparison.json()['fixes'], 0)
                draft = await client.post(f"/api/runs/{broken['id']}/regression-draft")
                self.assertEqual(draft.status_code, 201)
                self.assertEqual((await client.get(f"/api/regression-drafts/{draft.json()['id']}/export")).json(), draft.json())
                self.assertEqual((await client.post(f"/api/runs/{fixed['id']}/regression-draft")).status_code, 422)
                self.assertEqual((await client.post('/api/regressions/run', json={'profile': '../escape'})).status_code, 422)
                scored = await client.post('/api/audio/score', json={'reference': 'book friday', 'hypothesis': 'book monday'})
                self.assertEqual(scored.status_code, 201)
                self.assertEqual(scored.json()['metrics']['wer']['value'], .5)
                self.assertEqual((await client.post('/api/audio/score', json={'reference': '...', 'hypothesis': ''})).status_code, 422)
