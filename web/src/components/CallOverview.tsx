import { duration } from '../lib';
import type { CallSummary } from '../types';
import ReplyWaitChart from './ReplyWaitChart';

// Validated categorical palette (light surface): speaking, thinking, listening. Other states are neutral.
const STATES: { state: string; label: string; color: string }[] = [
  { state: 'speaking', label: 'Agent speaking', color: '#2f8a50' },
  { state: 'thinking', label: 'Agent thinking', color: '#e0a526' },
  { state: 'listening', label: 'Agent listening', color: '#6a4fc2' },
];
const OTHER = '#d3d9cf';
const colorFor = (state: string) => STATES.find(item => item.state === state)?.color ?? OTHER;
const seconds = (ms: number) => `${(ms / 1000).toFixed(1)}s`;

function Tile({ label, value, note, warn = false }: { label: string; value: string; note?: string; warn?: boolean }) {
  return <div className={`stat ${warn ? 'warn' : ''}`}><span>{label}</span><strong>{value}</strong>{note && <small>{note}</small>}</div>;
}

export default function CallOverview({ summary, onSelectEvent }: { summary: CallSummary; onSelectEvent: (id: string) => void }) {
  const total = summary.duration_ms || 1;
  const segments = summary.agent_states.filter(segment => segment.end_ms > segment.start_ms);
  const limit = summary.slow_reply_ms ?? 2000;
  const measured = summary.wait_p50_ms != null;
  const interrupted = summary.interruptions ?? 0;
  return (
    <section className="call-overview" aria-label="Call summary">
      <div className="stats">
        <Tile label="Duration" value={duration(summary.duration_ms)} />
        <Tile label="Caller turns" value={String(summary.caller_turns)} />
        <Tile label="Agent replies" value={String(summary.agent_turns)} note={interrupted ? `${interrupted} interrupted by caller` : undefined} />
        {measured
          ? <Tile label="Typical wait for a reply" value={seconds(summary.wait_p50_ms!)} warn={summary.wait_p50_ms! > limit}
              note={`slowest ${seconds(summary.wait_max_ms!)}`} />
          : <Tile label="Longest thinking pause" value={summary.longest_thinking_ms == null ? '—' : seconds(summary.longest_thinking_ms)} />}
        <Tile label="Tool calls" value={String(summary.tool_calls)} note={summary.retries ? `${summary.retries} retried` : undefined} />
      </div>
      {summary.replies && <ReplyWaitChart replies={summary.replies} limit={limit} onSelect={onSelectEvent} />}
      {segments.length > 0 && (
        <div className="state-strip">
          <div className="strip-heading">
            <h3>What the agent was doing</h3>
            <ul className="legend">
              {STATES.map(item => <li key={item.state}><span style={{ background: item.color }} />{item.label}</li>)}
              <li><span style={{ background: OTHER }} />Other</li>
            </ul>
          </div>
          <div className="strip" role="img" aria-label={`Agent state over ${duration(summary.duration_ms)}`}>
            {segments.map(segment => {
              const length = segment.end_ms - segment.start_ms;
              const tip = `${segment.state} · ${duration(segment.start_ms)}–${duration(segment.end_ms)} (${seconds(length)})`;
              return <span key={segment.start_ms} title={tip} style={{ flexGrow: length / total, background: colorFor(segment.state) }} />;
            })}
          </div>
          <div className="strip-axis"><span>0s</span><span>{duration(summary.duration_ms)}</span></div>
        </div>
      )}
      {!summary.complete && <p className="subtle">Early events were dropped from this long call, so the counts may be low.</p>}
    </section>
  );
}
