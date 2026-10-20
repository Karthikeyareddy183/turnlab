import { useState } from 'react';
import { checkName, post } from '../lib';
import type { Report, RunSummary } from '../types';

interface Comparison { regressions: number; fixes: number; remaining_failures: number; checks: { id: string; change: string; baseline_passed: boolean; candidate_passed: boolean }[] }

const PROFILES = [
  { value: 'corrected', label: 'Working version (should pass)' },
  { value: 'fault_memory', label: 'Broken memory (should fail)' },
  { value: 'fault_duplicate_booking', label: 'Double-booking bug (should fail)' },
];
const CHANGE: Record<string, string> = { regressed: 'Newly broken', fixed: 'Fixed', unchanged: 'No change' };

export default function RegressionLab({ runs, onRun, textAvailable }: { runs: RunSummary[]; onRun: (report: Report) => void; textAvailable: boolean }) {
  const [profile, setProfile] = useState('corrected');
  const [baseline, setBaseline] = useState('');
  const [candidate, setCandidate] = useState('');
  const [comparison, setComparison] = useState<Comparison | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [reference, setReference] = useState('');
  const [hypothesis, setHypothesis] = useState('');
  const [score, setScore] = useState<number | null>(null);
  const checkRuns = runs.filter(run => ['reference_execution', 'agent_text_execution'].includes(run.mode));

  async function attempt(action: () => Promise<void>) {
    setBusy(true); setError('');
    try { await action(); } catch (failure) { setError((failure as Error).message); } finally { setBusy(false); }
  }
  const runChecks = (path: string, body: unknown) => attempt(async () => {
    const report = await post<Report>(path, body);
    setBaseline(candidate); setCandidate(report.id); setComparison(null); onRun(report);
  });
  const compare = () => attempt(async () => {
    setComparison(null);
    setComparison(await post<Comparison>('/api/regressions/compare', { baseline_id: baseline, candidate_id: candidate }));
  });
  const scoreTranscript = () => attempt(async () => {
    setScore(null);
    const report = await post<Report>('/api/audio/score', { reference, hypothesis });
    setScore(report.metrics?.wer?.value ?? null); onRun(report);
  });
  const option = (run: RunSummary) => <option key={run.id} value={run.id}>{run.title} · {run.status} · {run.id.slice(0, 8)}</option>;

  return (
    <details className="regression-lab">
      <summary>Check memory and booking safety <span>Run built-in checks, then compare two runs to see what broke or got fixed.</span></summary>
      <div className="lab-body">
        <p>Runs four checks: remembering a corrected date, keeping each user's memory private, forgetting on expiry or deletion, and never booking twice. Runs locally, with no AI model and no cost.</p>
        <div className="lab-controls">
          <label>Version to check
            <select value={profile} onChange={event => setProfile(event.target.value)}>
              {PROFILES.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}
            </select>
          </label>
          <button className="button primary" onClick={() => void runChecks('/api/regressions/run', { profile })} disabled={busy}>Run checks</button>
        </div>
        <p>Or run the same booking conversation through a real AI model to see whether it uses the tools correctly. Uses Groq credits (up to six requests).</p>
        <button className="button secondary" disabled={busy || !textAvailable} title={textAvailable ? undefined : 'Add GROQ_API_KEY to .env and restart'}
          onClick={() => void runChecks('/api/regressions/text', {})}>{busy ? 'Running…' : 'Run with Groq'}</button>

        <h3 className="lab-step">Compare two runs</h3>
        <p>Pick an earlier run and a later one of the same kind. Your last two runs are filled in automatically.</p>
        <div className="lab-controls">
          <label>Before<select value={baseline} onChange={event => { setBaseline(event.target.value); setComparison(null); }}><option value="">Choose a run</option>{checkRuns.map(option)}</select></label>
          <label>After<select value={candidate} onChange={event => { setCandidate(event.target.value); setComparison(null); }}><option value="">Choose a run</option>{checkRuns.map(option)}</select></label>
          <button className="button secondary" disabled={busy || !baseline || !candidate || baseline === candidate} onClick={() => void compare()}>Compare</button>
        </div>
        {comparison && (
          <section aria-label="Comparison" className="comparison">
            <p><strong>{comparison.regressions} newly broken · {comparison.fixes} fixed · {comparison.remaining_failures} still failing</strong></p>
            <table>
              <thead><tr><th>Check</th><th>Before</th><th>After</th><th>Change</th></tr></thead>
              <tbody>{comparison.checks.map(row => (
                <tr key={row.id}><td>{checkName(row.id)}</td><td>{row.baseline_passed ? 'Passed' : 'Failed'}</td><td>{row.candidate_passed ? 'Passed' : 'Failed'}</td><td>{CHANGE[row.change] ?? row.change}</td></tr>
              ))}</tbody>
            </table>
          </section>
        )}

        <details className="transcript-lab">
          <summary>Measure speech-to-text accuracy</summary>
          <p>Paste what was actually said and what the speech-to-text heard (English). This counts wrong, missing and extra words. It does not measure voice quality or speed.</p>
          <label>What was said<textarea maxLength={20000} value={reference} onChange={event => setReference(event.target.value)} /></label>
          <label>What was heard<textarea maxLength={20000} value={hypothesis} onChange={event => setHypothesis(event.target.value)} /></label>
          <button className="button secondary" disabled={busy || !reference.trim()} onClick={() => void scoreTranscript()}>Measure accuracy</button>
          {score !== null && <p role="status">Word error rate: {(score * 100).toFixed(2)}% (lower is better). Saved to your tests.</p>}
        </details>
        {error && <p className="notice error" role="alert">{error}</p>}
      </div>
    </details>
  );
}
