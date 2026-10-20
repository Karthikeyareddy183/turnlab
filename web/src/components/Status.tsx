import { friendly } from '../lib';

const labels: Record<string, string> = {
  active: 'Live', closed: 'Ended', failed: 'Failed', completed: 'Completed', passed: 'Passed', incomplete: 'Incomplete',
};

export default function Status({ value, stale = false }: { value: string; stale?: boolean }) {
  const tone = stale || ['failed', 'incomplete', 'uncertain'].includes(value) ? 'warning'
    : ['active', 'passed'].includes(value) ? 'positive' : 'muted';
  return <span className={`status ${tone}`}><span />{stale ? 'Updates stopped' : labels[value] ?? friendly(value)}</span>;
}
