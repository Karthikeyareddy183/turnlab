import { useEffect, useState } from 'react';
import { ArrowRight, Waveform } from '@phosphor-icons/react';
import { api, isCall } from './lib';
import type { Catalog, Health, Page, Report } from './types';
import RunDetail from './components/RunDetail';
import RunList from './components/RunList';
import TestingTools from './components/TestingTools';

type Feed = 'connecting' | 'connected' | 'reconnecting';

function useLiveCatalog() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [feed, setFeed] = useState<Feed>('connecting');
  const [error, setError] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    void api<Catalog>('/api/runs', { signal }).then(setCatalog).catch(failure => { if (!signal.aborted) setError((failure as Error).message); });
    const refreshHealth = () => { void api<Health>('/api/health', { signal }).then(setHealth).catch(() => { if (!signal.aborted) setHealth(null); }); };
    refreshHealth();
    const timer = window.setInterval(refreshHealth, 10000);
    const source = new EventSource('/api/events');
    source.onopen = () => setFeed('connected');
    source.addEventListener('runs', event => {
      try { setCatalog(JSON.parse((event as MessageEvent).data)); setError(''); setFeed('connected'); }
      catch { setError('An update could not be read. Reload to try again.'); }
    });
    source.addEventListener('feed_error', () => setError('Some reports could not be loaded. Showing the last available data.'));
    source.onerror = () => setFeed('reconnecting');
    return () => { controller.abort(); source.close(); window.clearInterval(timer); };
  }, []);

  const refresh = () => api<Catalog>('/api/runs').then(setCatalog).catch(failure => setError((failure as Error).message));
  return { catalog, health, feed, error, refresh };
}

export default function App() {
  const params = new URLSearchParams(location.search);
  const [page, setPage] = useState<Page>(params.get('view') === 'tests' ? 'tests' : 'calls');
  const [selected, setSelected] = useState<string | null>(params.get('run'));
  const [fresh, setFresh] = useState<Report | undefined>();
  const { catalog, health, feed, error, refresh } = useLiveCatalog();

  const runs = catalog?.runs ?? [];
  const scoped = runs.filter(run => isCall(run) === (page === 'calls'));
  const calls = runs.filter(isCall);
  const liveCalls = calls.filter(call => call.status === 'active' && !call.stale).length;
  const selectedSummary = runs.find(run => run.id === selected);

  function choose(id: string | null, nextPage: Page = page) {
    setSelected(id); setPage(nextPage); setFresh(undefined);
    history.replaceState(null, '', `?view=${nextPage}${id ? `&run=${id}` : ''}`);
  }
  useEffect(() => {
    if (!selected && scoped.length) choose(scoped[0].id);
    if (selectedSummary && isCall(selectedSummary) !== (page === 'calls')) choose(selected, isCall(selectedSummary) ? 'calls' : 'tests');
  }, [catalog, selected, page]);

  const changePage = (next: Page) => choose(runs.find(run => isCall(run) === (next === 'calls'))?.id ?? null, next);
  function acceptRun(report: Report) {
    choose(report.id, 'tests'); setFresh(report); void refresh();
  }
  const sync = health?.synchronization;

  return <div className="min-h-[100dvh]">
    <a className="skip-link" href="#workspace">Skip to content</a>
    <header className="app-header">
      <div className="header-inner">
        <a className="brand" href="/" aria-label="TurnLab home"><Waveform size={26} weight="bold" />TurnLab</a>
        <nav aria-label="Main navigation">
          <button aria-current={page === 'calls' ? 'page' : undefined} onClick={() => changePage('calls')}>Calls</button>
          <button aria-current={page === 'tests' ? 'page' : undefined} onClick={() => changePage('tests')}>Testing</button>
        </nav>
        <span className={`feed-state ${feed}`} role="status" title="Connection between this page and the local TurnLab server">
          <span />{feed === 'connected' ? 'Dashboard online' : feed === 'connecting' ? 'Connecting…' : 'Server unreachable, retrying…'}
        </span>
      </div>
    </header>
    <main id="workspace" className="mx-auto max-w-[1400px] px-5 py-8 md:px-9 md:py-10">
      <div className="page-heading">
        <div>
          <h1>{page === 'calls' ? 'Your calls' : 'Testing'}</h1>
          <p>{page === 'calls' ? 'What failed during each call, what fixed itself, and what needs you.' : 'Try TurnLab safely, or check your agent before and after a change.'}</p>
        </div>
        <span className="collection-note">
          {page === 'calls' ? <>{calls.length} {calls.length === 1 ? 'call' : 'calls'}{liveCalls > 0 && <> · <b className="live-count">{liveCalls} live now</b></>}</> : 'Tests never appear under Calls.'}
        </span>
      </div>
      {error && <div className="notice error" role="alert">{error}<button className="text-button" onClick={() => location.reload()}>Reload</button></div>}
      {!!catalog?.skipped_reports && <p className="notice warning">{catalog.skipped_reports} reports could not be read and are hidden.</p>}
      {page === 'tests' && <TestingTools runs={runs} onRun={acceptRun} textAvailable={health?.text_evaluation_available ?? false} />}
      <section className="inspector" aria-label={page === 'calls' ? 'Call browser' : 'Test browser'}>
        <RunList key={page} page={page} catalog={catalog} runs={scoped} loadFailed={!!error} selected={selected} onSelect={id => choose(id)} />
        <div className="run-detail">
          {selected
            ? <RunDetail key={selected} runId={selected} summary={selectedSummary} health={health} initial={fresh?.id === selected ? fresh : undefined} />
            : <div className="detail-empty">
                <Waveform size={34} />
                <h2>{page === 'calls' ? 'Your next call will appear here' : 'Choose a test to see its results'}</h2>
                <p>{page === 'calls' ? 'Start your voice agent (agent.py console) and talk to it. The call shows up here within a second.' : 'Start with the sample failure above.'}</p>
                {page === 'calls' && <button className="text-button" onClick={() => changePage('tests')}>Try a demo instead <ArrowRight size={16} /></button>}
              </div>}
        </div>
      </section>
      <footer className="page-footer">
        <span>Reports are saved on this computer in .turnlab/runs</span>
        <details>
          <summary>{sync?.state === 'error' || sync?.state === 'configuration_error' ? 'Cloud backup needs attention' : 'Cloud backup'}</summary>
          <p>{sync?.configured || sync?.state === 'configuration_error' ? `Supabase: ${sync.state}${sync.last_error ? ` · ${sync.last_error}` : ''}` : 'Off. Optional; see docs/dashboard.md to connect Supabase.'}</p>
        </details>
      </footer>
    </main>
  </div>;
}
