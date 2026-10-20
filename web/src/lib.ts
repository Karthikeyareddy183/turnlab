import type { RunSummary } from './types';

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options);
  if (!response.ok) {
    let message = `Could not load this information (${response.status}). Please retry.`;
    try {
      const body = await response.json();
      if (typeof body.detail === 'string') message = body.detail;
    } catch { /* Use the fallback for non-JSON errors. */ }
    throw new Error(message);
  }
  return response.json();
}

export const post = <T,>(path: string, body?: unknown) => api<T>(path, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  ...(body === undefined ? {} : { body: JSON.stringify(body) }),
});

export const friendly = (value: string) => value.replaceAll('_', ' ');

export const date = (value: string) =>
  new Date(value).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });

export function duration(ms: number) {
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${String(seconds % 60).padStart(2, '0')}s`;
}

// Readable names for the built-in reference suite cases (src/turnlab/regression.py).
const CASE_NAMES: Record<string, string> = {
  correction: 'Remembers the corrected date',
  isolation: 'Keeps memory private to each user',
  'expiry-deletion': 'Forgets after expiry or deletion',
  'duplicate-write': 'Never books twice',
};

export function checkName(id: string) {
  const [prefix, step] = id.split(':');
  return CASE_NAMES[prefix] ? `${CASE_NAMES[prefix]} (step ${step})` : friendly(id);
}

export const isCall = (run: { mode: string }) => run.mode === 'livekit_session';

export const runTitle = (run: RunSummary) => isCall(run) ? 'Voice call' : run.title;

export function issueLabel(run: RunSummary) {
  const review = run.needs_review_count ?? run.incident_count + run.failed_check_count;
  const recovered = run.recovered_count ?? 0;
  if (!review && !recovered) return 'No issues';
  return [review && `${review} to review`, recovered && `${recovered} recovered`].filter(Boolean).join(' · ');
}
