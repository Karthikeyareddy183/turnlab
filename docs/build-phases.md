# TurnLab build phases

The selected product combines live-call monitoring, predefined recovery, post-call diagnosis, and regression checks. Application services run locally; Groq and Deepgram provide inference, and hosted Supabase stores selected metadata. Phases are delivery milestones, not guaranteed dates. The 4–6 week goal remains a planning estimate.

## Phase 1 Incident and recovery foundation

Status: Implemented; verification results are recorded in the development instructions.

- Versioned fixture grading, CLI, local reports, and FastAPI fixture endpoints.
- Provider-independent async tool wrapper with correlated operation/attempt events.
- Detection of raised tool errors and deadlines, with bounded incident evidence.
- Explicit recovery policies: safe reads, declared idempotent writes with keys, and unsafe/default operations.
- Per-operation and per-call retry limits; non-transient errors do not automatically retry.
- Uncertain writes request human review instead of blindly repeating the action.
- An executable local demo and tests for cancellation, timeout, evidence limits, and recovery behavior.

Exit check: demo lookup recovers after one transient failure; demo write commits once and returns an uncertain outcome without a second commit. This phase executes fixture callbacks, not live speech. A declared idempotent operation still requires a real adapter guarantee in later phases.

## Phase 2 LiveKit voice integration

Status: Integration implemented; provider credential smoke tests and local worker registration verified. End-to-end microphone conversation acceptance remains pending. See [voice quickstart](voice-quickstart.md).

- Extract settings and introduce an explicit local execution profile.
- Migrate the reference agent to Groq LLM and Deepgram STT/TTS; select supported model/voice defaults and pin tested SDK dependencies.
- Wrap trusted tools using Phase 1 policies and record session/turn/operation correlation.
- Capture provider errors through supported SDK hooks; keep monitoring and database I/O outside audio-critical callbacks.
- Demonstrate a tool failure during a local LiveKit conversation and preserve evidence when the caller disconnects.

Exit check: a real local call emits an incident and a truthful recovery outcome. Requires configured provider credentials and local media-server availability. Do not publish those credentials in reports or commit them.

## Phase 3 Persistence and live dashboard

Status: Dashboard and local live feed implemented and browser-tested. Hosted Supabase credentials/table access and metadata writes now pass. See [dashboard guide](dashboard.md).

- Supabase schema/migrations for sessions, runs, incidents, and selected metrics.
- Local artifact references, batched synchronization, and visible persistence failures.
- React/TypeScript dashboard backed by FastAPI: active session, incident list, evidence timeline, recovery outcomes.
- Server-sent incident updates with connection/reconnect and evidence-gap indicators.

Exit check: dashboard shows an incident from Phase 2, and its report remains inspectable after the call. A Supabase outage does not terminate the call.

## Phase 4 Post-call diagnosis

Status: Evidence summaries, investigation suggestions, and opt-in Groq hypotheses implemented. Model references are validated and stale evidence is flagged; no fixes are applied automatically. See [dashboard guide](dashboard.md).

- Structured evidence summaries, confirmed observations, unresolved outcomes, and missing signals.
- Optional Groq diagnosis with validated event references and clearly labelled hypotheses.
- Developer-reviewed fix suggestions; no live code/prompt editing.

Exit check: an incident report explains what is known, what remains unknown, recovery attempted, and a reviewable next action. Diagnosis-provider failure produces an unavailable status rather than a fabricated explanation.

## Phase 5 Regression and memory evaluation

Status: Implemented for this local pilot: executable reference suite, optional real Groq text/tool case, matching-contract comparisons, review-required incident worksheets, scoped memory lifecycle checks, English WER scoring, and an opt-in recorded WAV upload adapter. Full recorded-file adapter acceptance and voice accuracy/latency benchmarking remain separate. See [regression and pilot guide](regression-and-pilot.md).

- Convert reviewed incidents into versioned test scenarios.
- Run reference-agent text scenarios, memory correction/expiry/isolation checks, and baseline comparisons.
- Add recorded-audio scoring with explicit reference transcripts and language normalization.
- Keep objective state assertions authoritative over optional semantic judges.

Exit check: a deliberately introduced regression fails, a real fix is applied outside an active call, and a rerun verifies it. Saved event playback alone is not a rerun.

## Phase 6 Reliability and pilot release

Status: Local hardening implemented and tested: interrupted atomic writes, disk outage recovery, corrupt/partial/oversized artifacts, readiness inspection, bounded model execution, repeatable offline demo, setup scripts, and Windows CI configuration. Remote CI execution, full microphone acceptance, and external developer feedback are still pending. See [regression and pilot guide](regression-and-pilot.md).

- Monitor overload, cancellation, repeated errors, provider outages, and partial-artifact recovery.
- Review credential handling, access boundaries, audio retention, and installation reproducibility.
- Local end-to-end demo, support matrix, measured results, and external developer feedback.
- Add automated duplex interruption measurements only if the measurement path can be validated; otherwise mark them unavailable.

Exit check: another developer can run the project locally, reproduce an incident, and inspect its evidence. Report actual sample sizes and limitations; do not claim production scale from a local demo.
