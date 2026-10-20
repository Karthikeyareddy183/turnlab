import { useEffect, useState } from 'react';
import { DownloadSimple } from '@phosphor-icons/react';
import { api, checkName, friendly } from '../lib';
import type { EvidenceEvent, Report } from '../types';
import Status from './Status';

const views = ['Events', 'Test results', 'Raw report'];
const sec = (ms?: number) => ms == null ? null : `${(ms / 1000).toFixed(2)}s`;

function describe(event: EvidenceEvent) {
  const parts = event.type === 'agent_reply'
    ? [event.wait_ms != null ? `caller waited ${sec(event.wait_ms)}` : 'wait not measured',
       event.llm_ms != null && `AI model ${sec(event.llm_ms)}`, event.tts_ms != null && `voice ${sec(event.tts_ms)}`,
       event.interrupted && 'interrupted']
    : event.type === 'caller_turn'
      ? [event.stt_ms != null ? `transcribed in ${sec(event.stt_ms)}` : 'Caller finished speaking']
      : event.type === 'false_interruption'
        ? [event.resumed ? 'Agent resumed speaking' : 'Agent stopped for noise']
        : [event.tool ?? event.state ?? event.source ?? 'Session event', event.error_type, event.attempt && `attempt ${event.attempt}`];
  return parts.filter(Boolean).join(' · ');
}

interface Props {
  report: Report; timeline: EvidenceEvent[]; canDraft: boolean;
  open: boolean; onOpenChange: (open: boolean) => void; highlight: string | null;
  onError: (message: string) => void;
}

export default function TechnicalDetails({ report, timeline, canDraft, open, onOpenChange, highlight, onError }: Props) {
  const [tab, setTab] = useState('Events');
  const [draftId, setDraftId] = useState<string | null>(null);
  const [draftBusy, setDraftBusy] = useState(false);

  useEffect(() => { setTab('Events'); setDraftId(null); }, [report.id]);
  useEffect(() => { if (highlight) setTab('Events'); }, [highlight]);
  useEffect(() => {
    if (!open || !highlight) return;
    const frame = requestAnimationFrame(() => document.getElementById(`evidence-${highlight}`)?.scrollIntoView({ block: 'center' }));
    return () => cancelAnimationFrame(frame);
  }, [open, highlight, tab]);

  async function createDraft() {
    const id = report.id;
    setDraftBusy(true);
    try {
      const draft = await api<{ id: string }>(`/api/runs/${id}/regression-draft`, { method: 'POST' });
      if (report.id === id) setDraftId(draft.id);
    } catch (failure) { onError((failure as Error).message); }
    finally { setDraftBusy(false); }
  }

  function onTabKey(event: React.KeyboardEvent<HTMLDivElement>) {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const current = views.indexOf(tab);
    const index = event.key === 'Home' ? 0 : event.key === 'End' ? views.length - 1
      : (current + (event.key === 'ArrowRight' ? 1 : -1) + views.length) % views.length;
    setTab(views[index]);
    event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]')[index]?.focus();
  }

  return (
    <details className="technical" open={open} onToggle={event => onOpenChange(event.currentTarget.open)}>
      <summary>Technical details</summary>
      <p className="coverage">{report.coverage}</p>
      <p className="run-id">Report ID: {report.id}</p>
      <div className="technical-actions">
        <a className="button secondary" href={`/api/runs/${report.id}/export`}><DownloadSimple size={15} />Download report</a>
        {canDraft && <button className="button secondary" disabled={draftBusy} onClick={() => void createDraft()}>Create test worksheet</button>}
        {draftId && <a className="text-button" href={`/api/regression-drafts/${draftId}/export`}>Download worksheet (fill in before use)</a>}
      </div>
      <div className="tabs" role="tablist" aria-label="Evidence views" onKeyDown={onTabKey}>
        {views.map((item, index) => (
          <button key={item} id={`evidence-tab-${index}`} role="tab" aria-selected={tab === item} aria-controls="evidence-panel"
            tabIndex={tab === item ? 0 : -1} onClick={() => setTab(item)}>{item}</button>
        ))}
      </div>
      <div role="tabpanel" id="evidence-panel" aria-labelledby={`evidence-tab-${views.indexOf(tab)}`}>
        {tab === 'Events' && (!timeline.length ? <p className="subtle">No events were recorded.</p> : (
          <ol className="timeline">
            {timeline.map((event, index) => (
              <li key={event.id ?? index} id={`evidence-${event.id ?? index}`} className={highlight === event.id ? 'highlighted' : ''}>
                <span title="Time since the session started">{((event.offset_ms ?? 0) / 1000).toFixed(2)}s</span>
                <div>
                  <strong>{friendly(event.type)}</strong>
                  <p>{describe(event)}</p>
                </div>
              </li>
            ))}
          </ol>
        ))}
        {tab === 'Test results' && (report.checks?.length ? report.checks.map(check => (
          <div className="assertion" key={check.id}>
            <div><h4>{checkName(check.id)}</h4><Status value={check.passed ? 'passed' : 'failed'} /></div>
            <dl>
              <dt>Expected</dt><dd><code>{JSON.stringify(check.expected)}</code></dd>
              <dt>Actual</dt><dd><code>{JSON.stringify(check.actual)}</code></dd>
            </dl>
          </div>
        )) : <p className="subtle">No checks were run for this report.</p>)}
        {tab === 'Raw report' && <pre className="raw-report">{JSON.stringify(report, null, 2)}</pre>}
      </div>
    </details>
  );
}
