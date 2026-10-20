import { useEffect, useState } from 'react';
import { api, post } from '../lib';
import type { Report, RunSummary, Scenario } from '../types';
import RegressionLab from './RegressionLab';

export default function TestingTools({ runs, onRun, textAvailable }: { runs: RunSummary[]; onRun: (report: Report) => void; textAvailable: boolean }) {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenario, setScenario] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    void api<Scenario[]>('/api/scenarios').then(items => { setScenarios(items); setScenario(items[0]?.id ?? ''); }).catch(() => {});
  }, []);

  async function execute(path: string, body?: unknown) {
    setBusy(true); setError('');
    try { onRun(await post<Report>(path, body)); } catch (failure) { setError((failure as Error).message); } finally { setBusy(false); }
  }

  return (
    <section className="testing-tools" aria-label="Testing tools">
      <div className="demo-row">
        <div>
          <h2>Try a sample failure</h2>
          <p>Simulates a ticket lookup that fails and then recovers, and a booking that times out. Free, with no call or AI model.</p>
        </div>
        <button className="button primary" disabled={busy} onClick={() => void execute('/api/demos/tool-monitor')}>{busy ? 'Running…' : 'Run demo'}</button>
      </div>
      {error && <p className="notice error" role="alert">{error}</p>}
      <RegressionLab runs={runs} onRun={onRun} textAvailable={textAvailable} />
      <details className="fixture-picker">
        <summary>Grade a saved example conversation</summary>
        <div className="lab-controls">
          <label htmlFor="scenario">Example</label>
          <select id="scenario" value={scenario} onChange={event => setScenario(event.target.value)}>
            {scenarios.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
          <button className="button secondary" disabled={busy || !scenario} onClick={() => void execute('/api/runs', { scenario_id: scenario })}>Grade</button>
        </div>
        <p>Checks a recorded example against its expected outcome. Some examples are broken on purpose and should fail.</p>
      </details>
    </section>
  );
}
