export interface RunSummary {
  id: string; title: string; mode: string; status: string; created_at: string; updated_at: string;
  stale: boolean; incident_count: number; failed_check_count: number; recovered_count: number; needs_review_count: number;
  fingerprint: string;
}
export interface Catalog { runs: RunSummary[]; skipped_reports: number; limit: number }
export interface EvidenceEvent { id?: string; type: string; tool?: string; attempt?: number; offset_ms?: number; state?: string; source?: string; error_type?: string;
  wait_ms?: number; llm_ms?: number; tts_ms?: number; stt_ms?: number; interrupted?: boolean; resumed?: boolean; data?: unknown }
export interface Incident { id: string; kind: string; tool?: string; source?: string; cause?: string; error_type?: string; recovery?: string; recovery_outcome?: string; evidence_event_id?: string }
export interface Assertion { id: string; kind: string; passed: boolean; expected: unknown; actual: unknown; event_indexes: number[] }
export interface Report {
  id: string; status: string; mode: string; coverage: string; created_at: string; events: EvidenceEvent[];
  session_events?: EvidenceEvent[]; incidents?: Incident[]; checks?: Assertion[];
  telemetry?: { complete?: boolean; dropped_events?: number; dropped_incidents?: number; persistence_errors?: number };
  retries_used?: number;
  metrics?: Record<string, { status: string; value: number | null }>;
}
export interface Finding { id: string; kind: string; title?: string; tool?: string | null; observation: string; cause_status: string; suggestion: string; recovery: string; recovery_outcome: string; evidence_event_id?: string; evidence_available: boolean }
export interface StateSegment { state: string; start_ms: number; end_ms: number }
export interface ReplyTiming { id: string; offset_ms: number; wait_ms?: number; llm_ms?: number; tts_ms?: number; interrupted: boolean }
export interface CallSummary {
  duration_ms: number; caller_turns: number; agent_turns: number; tool_calls: number; retries: number;
  provider_errors: number; longest_thinking_ms: number | null; agent_states: StateSegment[]; complete: boolean;
  wait_p50_ms?: number | null; wait_p95_ms?: number | null; wait_max_ms?: number | null; slow_reply_ms?: number | null;
  replies?: ReplyTiming[]; interruptions?: number; false_interruptions?: number;
}
export interface Analysis { method: string; findings: Finding[]; call_summary: CallSummary | null; limitations: string[] }
export interface Health { diagnosis_available: boolean; text_evaluation_available: boolean; synchronization: { configured: boolean; state: string; last_error: string | null; last_success: string | null } }
export interface Diagnosis { run_id: string; state: string; stale?: boolean; model?: string; hypotheses?: { finding_id: string; hypothesis: string; evidence_event_ids: string[]; investigation: string }[] }
export interface Scenario { id: string; name: string; mode: string }
export type Page = 'calls' | 'tests';
