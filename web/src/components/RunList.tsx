import { useState } from 'react';
import { MagnifyingGlass } from '@phosphor-icons/react';
import { date, issueLabel, runTitle } from '../lib';
import type { Catalog, Page, RunSummary } from '../types';
import Status from './Status';

interface Props { page: Page; catalog: Catalog | null; runs: RunSummary[]; loadFailed: boolean; selected: string | null; onSelect: (id: string) => void }

export default function RunList({ page, catalog, runs, loadFailed, selected, onSelect }: Props) {
  const [query, setQuery] = useState('');
  const calls = page === 'calls';
  const filtered = runs.filter(run => `${runTitle(run)} ${date(run.created_at)} ${run.id}`.toLowerCase().includes(query.toLowerCase()));
  return (
    <aside className="run-list">
      <div className="section-heading"><h2>{calls ? 'Recent calls' : 'Recent tests'}</h2><span>{runs.length}</span></div>
      <label className="search">
        <MagnifyingGlass size={17} />
        <input aria-label={calls ? 'Search calls' : 'Search tests'} placeholder={calls ? 'Search by date or call ID' : 'Search tests'}
          value={query} onChange={event => setQuery(event.target.value)} />
      </label>
      <div className="run-items">
        {!catalog && !loadFailed ? <div className="skeleton" aria-label="Loading list" />
          : !filtered.length ? <p className="list-empty">{query ? 'No matches. Try another search.' : calls ? 'No calls yet. Start your voice agent to see one here.' : 'No tests yet. Run the demo above.'}</p>
          : filtered.map(run => (
            <button key={run.id} aria-pressed={run.id === selected} className={`run-item ${run.id === selected ? 'selected' : ''}`} onClick={() => onSelect(run.id)}>
              <div><strong>{runTitle(run)}</strong><span className={run.needs_review_count ? 'needs-review' : ''}>{issueLabel(run)}</span></div>
              <time>{date(run.created_at)}</time>
              <Status value={run.status} stale={run.stale} />
            </button>
          ))}
      </div>
      <p className="list-footnote">Showing the {catalog?.limit ?? 100} most recent reports.</p>
    </aside>
  );
}
