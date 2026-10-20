# Live monitoring and post-call diagnosis

Status: Accepted product scope; implemented for the local pilot (see "Current implementation boundary" below). Date: 2026-10-15.

TurnLab will observe instrumented LiveKit calls while they run, detect a small set of failures, and invoke predefined recovery policies through the agent adapter. After the call, it will analyze collected evidence, suggest fixes, and help create reviewed regression scenarios. It will not automatically edit application code or prompts in an active call.

## First supported incidents

| Signal | What we can establish | Initial response |
| --- | --- | --- |
| Tool raises an error | The named operation failed with the recorded error | Explain failure or retry only when the operation's policy allows it |
| Tool exceeds its configured deadline | The result was not received before the deadline; an external write may still have committed | Check operation status if supported; never blindly retry an uncertain write |
| Speech/model provider reports failure | A specific request failed; underlying network/provider cause may be unknown | Use an explicitly configured fallback, or request a human callback |
| Response exceeds a configured threshold | The available timing signal exceeded the threshold | Notify the operator; agent may acknowledge the wait once if appropriate |
| Instrumented memory access violates scope | A tenant/user boundary violation was attempted | Prevent the result from reaching the model and escalate |

Start with tool errors and timeouts. Speech-provider errors follow after live adapters are connected. Slow responses and memory violations require the corresponding timing/enforcement instrumentation. We cannot infer every problem from an audio recording or transcript alone.

## During the call

1. The agent adapter emits normalized events with session, turn, and operation IDs, source, and timestamps.
2. A bounded monitor evaluates deterministic rules and captures an incident with recent relevant events.
3. A policy selects an allowed recovery action; a tool failure does not automatically invoke an LLM or halt the whole call.
4. An agent-side executor applies the selected action, respecting cancellation, operation state, and retry budgets.
5. The local dashboard receives the incident, evidence, recovery attempt, and outcome.
6. Optional background diagnosis proposes an explanation. It is labelled as a hypothesis unless the evidence establishes the cause.

The monitoring queue must not block audio callbacks. Queue overflow produces a visible telemetry-gap marker and incomplete-evidence status. Database writes and LLM diagnosis run outside the audio-critical path. A monitoring failure must not terminate the conversation; enforcement at the actual tool/memory boundary remains active independently of the dashboard.

Retries apply only to allowlisted operations with explicit replay semantics. Read-only calls may retry within a bounded deadline. Writes require a stable idempotency key plus a documented adapter guarantee or a reconciled operation status. Default is no retry for an unknown operation. Limit recovery per operation and per call to prevent loops.

Initial recovery actions are bounded retry, a wait/failure message, and a visible human-review request. Do not claim a live human transfer unless a human participant is available and the transfer succeeds. With no configured recipient, record a callback/review request and tell the caller accurately. A provider fallback is enabled only after another provider/model is configured and tested; our single-provider starting configuration does not imply one exists.

## After the call

Produce an incident report containing:

- Observed failure, affected operation/turn, and direct evidence references.
- Confirmed cause where available, or explicitly labelled hypotheses with supporting and missing evidence.
- Recovery attempted, whether it succeeded, and what remained unresolved.
- Suggested configuration or code change for a developer to review.
- A proposed regression scenario built from redacted evidence and reviewed expected behavior.

Use objective checks first. Optional Groq analysis reads selected incident context, not an unlimited history, and returns a structured report with event references. Validate those references and mark diagnosis unavailable if the model fails. Do not expose chain-of-thought or present model confidence as a calibrated probability.

Turning a failure into a test means creating a scenario and rerunning the agent later. Saved-trace playback alone is not verification that a fix works. Human review is required before changing expected assertions or applying a proposed prompt/code fix.

## Interfaces and storage

- LiveKit adapter: event capture and application of supported agent-side recovery actions.
- Monitor: deterministic detection, deadline checks, incident deduplication, and bounded evidence snapshots.
- Recovery policy: explicit operation classification, retry budget, idempotency guarantees, and escalation options.
- FastAPI: incident list/detail plus server-sent events for the local dashboard; no unauthenticated general-purpose tool executor.
- React/TypeScript: active-call status, incident timeline, recovery outcomes, and post-call reports.
- Supabase: selected incident/run metadata, results, and persistent records.
- Local disk: detailed trace/audio artifacts, including partial artifacts when metadata synchronization fails.

The analysis engine consumes a normalized event contract. LiveKit is the first integration, not a prerequisite for analyzing imported compatible evidence. Imported historical evidence never triggers live recovery actions.

## Demonstration and acceptance

1. Inject a timeout into a read-only fixture operation during an instrumented local call. Show one allowed retry, a visible incident, and its actual outcome.
2. Inject a timeout after a write commits. Verify that the monitor reports an uncertain outcome and does not blindly repeat the write.
3. End the call and generate an evidence-linked incident report. Keep a deliberately unknown cause unknown.
4. Create a reviewed regression scenario, implement a fix outside the active call, and rerun it to verify the result.
5. Test repeated errors, exhausted retry budgets, duplicate/out-of-order events, monitoring queue overflow, cancellation, and unavailable database/diagnosis services.

Initial delivery is live detection plus post-call incident reports. Add bounded recovery after the detection path and operation contracts are tested. Full audio-quality scoring, autonomous debugging agents, multiple voice frameworks, production load claims, and automatic code changes are outside the first release.

## Current implementation boundary

Phase 1 supplies fixture grading and bounded tool recovery. Phase 2 connects that engine to a LiveKit reference agent, hooks selected SDK session/error events, and periodically persists local reports. Its worker registers with the local server. Phases 3 and 4 add the React dashboard, live report feed, evidence summaries, and optional Groq hypotheses. Phase 5 adds executable regression/model text cases, memory checks, comparison, and English transcript scoring. Phase 6 adds local reliability checks and pilot tooling. Hosted metadata writes/read-back and real Groq diagnosis/text evaluation pass. A full microphone conversation is deferred; other pilot acceptance limits are recorded in the [regression and pilot guide](regression-and-pilot.md). See [build phases](build-phases.md), [dashboard guide](dashboard.md), and [voice quickstart](voice-quickstart.md).
