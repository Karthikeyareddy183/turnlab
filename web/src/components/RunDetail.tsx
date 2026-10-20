import { useEffect, useRef, useState } from 'react';
import { CheckCircle, WarningCircle } from '@phosphor-icons/react';
import { api, date, isCall } from '../lib';
import type { Analysis, Diagnosis, Health, Report, RunSummary } from '../types';
import CallOverview from './CallOverview';
import IssueCard from './IssueCard';
import Status from './Status';
import TechnicalDetails from './TechnicalDetails';

/** Mounted once per selected run (keyed by ID), so all local state belongs to that run. */
export default function RunDetail({ runId, summary, health, initial }: { runId: string; summary?: RunSummary; health: Health | null; initial?: Report }) {
  const [report, setReport] = useState<Report | null>(initial ?? null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [diagnosis, setDiagnosis] = useState<Diagnosis | null>(null);
  const [loadError, setLoadError] = useState('');
  const [actionError, setActionError] = useState('');
  const [diagnosing, setDiagnosing] = useState(false);
  const [technicalOpen, setTechnicalOpen] = useState(false);
  const [highlight, setHighlight] = useState<string | null>(null);
  const mounted = useRef(true);
  useEffect(() => () => { mounted.current = false; }, []);

  const fingerprint = summary?.fingerprint;
  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    void Promise.all([
      api<Report>(`/api/runs/${runId}`, { signal }),
      api<Analysis>(`/api/runs/${runId}/analysis`, { signal }),
      api<Diagnosis>(`/api/runs/${runId}/diagnosis`, { signal }).catch(() => null),
    ]).then(([data, evidence, hypotheses]) => {
      setReport(data); setAnalysis(evidence); setDiagnosis(hypotheses); setLoadError('');
    }).catch(failure => { if (!signal.aborted) setLoadError((failure as Error).message); });
    return () => controller.abort();
  }, [runId, fingerprint]);

  async function requestDiagnosis() {
    setDiagnosing(true); setActionError('');
    try {
      const result = await api<Diagnosis>(`/api/runs/${runId}/diagnosis`, { method: 'POST' });
      if (mounted.current) setDiagnosis(result);
    } catch (failure) { if (mounted.current) setActionError((failure as Error).message); }
    finally { if (mounted.current) setDiagnosing(false); }
  }

  if (loadError) {
    return <div className="detail-empty" role="alert"><WarningCircle size={30} /><h2>Unable to load this report</h2><p>{loadError}</p>
      <button className="button secondary" onClick={() => location.reload()}>Reload</button></div>;
  }
  if (!report) return <div className="detail-loading" aria-label="Loading report"><div className="skeleton" /><div className="skeleton" /></div>;

  const call = isCall(report);
  const findings = analysis?.findings ?? [];
  const recovered = findings.filter(item => item.recovery_outcome === 'recovered').length;
  const review = findings.length - recovered;
  const timeline = [...(report.events ?? []), ...(report.session_events ?? [])].sort((a, b) => (a.offset_ms ?? 0) - (b.offset_ms ?? 0));
  const showEvidence = (id: string) => { setHighlight(id); setTechnicalOpen(true); };

  return <>
    <div className="detail-heading">
      <div><span className="subtle">{date(report.created_at)}</span><h2>{call ? 'Call overview' : summary?.title ?? 'Test results'}</h2></div>
      <Status value={report.status} stale={summary?.stale} />
    </div>
    <div className="detail-content">
      {summary?.stale && <p className="notice warning">This call stopped sending updates. It may have crashed, so its final state is unknown.</p>}
      {report.telemetry?.complete === false && <p className="notice warning">Some events were dropped, so this report is incomplete.</p>}
      {!!report.telemetry?.persistence_errors && <p className="notice warning">Some report updates could not be saved to disk.</p>}
      {analysis?.call_summary && <CallOverview summary={analysis.call_summary} onSelectEvent={id => showEvidence(id)} />}

      {!analysis ? <div className="skeleton" aria-label="Loading issues" /> : <>
        <div className="issue-summary">
          <h3>{findings.length ? `${findings.length} ${findings.length === 1 ? 'issue' : 'issues'}` : 'No issues found'}</h3>
          {findings.length > 0 && <p>{review} {review === 1 ? 'needs' : 'need'} review · {recovered} recovered</p>}
        </div>
        {!findings.length ? (
          <div className="no-findings"><CheckCircle size={25} />
            <p>{report.mode === 'transcript_scoring' ? 'Transcript scoring is complete.'
              : report.checks?.length ? `All ${report.checks.length} checks passed.` : 'No tool or voice service failures.'}</p>
          </div>
        ) : findings.map(finding => <IssueCard key={finding.id} finding={finding} onEvidence={showEvidence} />)}
      </>}

      {report.metrics?.wer?.status === 'measured' && (
        <p className="notice">Word error rate: {((report.metrics.wer.value ?? 0) * 100).toFixed(2)}% (lower is better).</p>
      )}

      {review > 0 && (
        <section className="investigation">
          <div>
            <h3>Want a second opinion?</h3>
            <p>{health?.diagnosis_available
              ? 'Ask AI for likely causes. Sends issue details to Groq (no transcripts or audio) and uses a small amount of credit.'
              : 'Add a GROQ_API_KEY to .env and restart to get AI suggestions.'}</p>
          </div>
          <button className="button secondary" disabled={diagnosing || !health?.diagnosis_available} onClick={() => void requestDiagnosis()}>
            {diagnosing ? 'Thinking…' : 'Suggest causes'}
          </button>
        </section>
      )}
      {actionError && <p className="notice error" role="alert">{actionError}</p>}
      {diagnosis?.run_id === report.id && diagnosis.state === 'available' && (
        <section className="model-diagnosis" aria-label="Possible causes">
          <h3>Possible causes</h3>
          <p className="subtle">AI suggestions. Verify before changing anything.</p>
          {diagnosis.stale && <p className="notice warning">The report changed after these suggestions were made. Ask again for fresh ones.</p>}
          {diagnosis.hypotheses?.map(item => <article key={item.finding_id}><h4>{item.hypothesis}</h4><p>{item.investigation}</p></article>)}
          {!diagnosis.hypotheses?.length && <p>No suggestions were returned.</p>}
        </section>
      )}

      <TechnicalDetails report={report} timeline={timeline} canDraft={findings.length > 0} open={technicalOpen}
        onOpenChange={setTechnicalOpen} highlight={highlight} onError={setActionError} />
    </div>
  </>;
}
