import { duration } from '../lib';
import type { ReplyTiming } from '../types';

const seconds = (ms: number) => `${(ms / 1000).toFixed(1)}s`;

function tip(reply: ReplyTiming, index: number) {
  const parts = [reply.llm_ms != null && `AI model ${seconds(reply.llm_ms)}`, reply.tts_ms != null && `voice ${seconds(reply.tts_ms)}`].filter(Boolean);
  return `Reply ${index + 1} at ${duration(reply.offset_ms)}: caller waited ${seconds(reply.wait_ms!)}`
    + (parts.length ? ` (${parts.join(', ')})` : '') + (reply.interrupted ? ' · interrupted' : '');
}

/** One bar per measured reply; bars over the slow limit are labelled and coloured as warnings. */
export default function ReplyWaitChart({ replies, limit, onSelect }: { replies: ReplyTiming[]; limit: number; onSelect: (id: string) => void }) {
  const measured = replies.filter(reply => reply.wait_ms != null);
  if (!measured.length) return null;
  const top = Math.max(limit, ...measured.map(reply => reply.wait_ms!)) * 1.15;
  const limitPosition = `${(limit / top) * 100}%`;
  return (
    <div className="wait-chart">
      <div className="strip-heading">
        <h3>How long the caller waited for each reply</h3>
        <ul className="legend">
          <li><span className="wait-swatch" />Reply</li>
          <li><span className="wait-swatch slow" />Slower than {seconds(limit)}</li>
        </ul>
      </div>
      <div className="wait-plot" role="list" aria-label="Wait before each reply">
        <div className="wait-limit" style={{ bottom: limitPosition }}><span>limit {seconds(limit)}</span></div>
        {measured.map((reply, index) => {
          const slow = reply.wait_ms! > limit;
          return (
            <button key={reply.id} role="listitem" className={`wait-bar ${slow ? 'slow' : ''}`} title={tip(reply, index)}
              aria-label={tip(reply, index)} onClick={() => onSelect(reply.id)}>
              {slow && measured.length <= 24 && <span className="wait-value">{seconds(reply.wait_ms!)}</span>}
              <span className="wait-fill" style={{ height: `${(reply.wait_ms! / top) * 100}%` }} />
            </button>
          );
        })}
      </div>
      <div className="strip-axis"><span>First reply</span><span>Last reply</span></div>
    </div>
  );
}
