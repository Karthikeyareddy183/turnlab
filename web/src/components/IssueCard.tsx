import { ArrowRight, CheckCircle, WarningCircle } from '@phosphor-icons/react';
import { checkName } from '../lib';
import type { Finding } from '../types';

function summary(finding: Finding, recovered: boolean) {
  if (recovered) return 'It failed, then an automatic retry succeeded. No action needed.';
  if (finding.recovery === 'request_human_review') return 'The result is uncertain, so it was not retried. Confirm what happened before trying again.';
  if (finding.kind === 'assertion_failed') return 'The result did not match what the check expected.';
  if (finding.kind === 'slow_response') return 'Nothing failed, but callers waited too long for some replies. Click a bar in the chart above to see each one.';
  if (finding.recovery === 'sdk_managed') return 'The voice SDK flagged this as recoverable and retries on its own. Look into it if it keeps happening.';
  return 'This was not recovered automatically. Check the details below.';
}

export default function IssueCard({ finding, onEvidence }: { finding: Finding; onEvidence: (id: string) => void }) {
  const recovered = finding.recovery_outcome === 'recovered';
  return (
    <article className="issue">
      <div className={`issue-icon ${recovered ? 'recovered' : ''}`}>
        {recovered ? <CheckCircle size={21} /> : <WarningCircle size={21} />}
      </div>
      <div className="issue-body">
        <div className="issue-heading">
          <h3>{finding.kind === 'assertion_failed' ? `Check failed: ${checkName(finding.id.replace(/^check:/, ''))}` : finding.title ?? finding.observation}</h3>
          <span className={`outcome ${recovered ? 'recovered' : ''}`}>{recovered ? 'Recovered' : 'Needs review'}</span>
        </div>
        <p>{summary(finding, recovered)}</p>
        <details className="issue-more">
          <summary>What happened?</summary>
          <p>{finding.observation}</p>
          <h4>What to check</h4>
          <p>{finding.suggestion}</p>
          {finding.evidence_event_id && (
            <button className="text-button" disabled={!finding.evidence_available} onClick={() => onEvidence(finding.evidence_event_id!)}>
              {finding.evidence_available ? 'Show in timeline' : 'Event no longer retained'} <ArrowRight size={14} />
            </button>
          )}
        </details>
      </div>
    </article>
  );
}
