# ADR 001 Local voice evaluation toolkit

Status: Partially accepted. The user selected the product direction, LiveKit Agents with a local LiveKit media server, local application execution with optional Groq LLM inference, Deepgram STT/TTS, hosted Supabase database persistence, and a FastAPI plus React/TypeScript dashboard. Final model/voice defaults and remaining technology choices are proposed.

Date: 2026-10-15.

## Context

The existing repository contains one LiveKit worker. The user wants a meaningful portfolio product for global/remote AI engineering roles, chose a voice-agent evaluation/debugging toolkit, and specified local execution, a 4–6 week timeline, and service selection one at a time.

## Options

| Option | Benefits | Costs | Appropriate when |
| --- | --- | --- | --- |
| Only use existing hosted simulation products | Broad functionality, little harness engineering | Hosted dependency; limited opportunity to demonstrate runner internals | Team primarily wants to test an application quickly |
| Build a general multi-provider evaluation SaaS | Broad market surface | Authentication, billing, hosting, adapters, security and acquisition exceed MVP scope | Proven demand and a funded team |
| Build a local LiveKit regression toolkit using SDK helpers | Direct reuse, inspectable artifacts, focused implementation | Narrow first integration; must validate differentiated value | Selected local portfolio/pilot scope |

## Proposed decisions and trade-offs

1. Retain LiveKit as the first integration and use its supported test helpers. A versioned adapter isolates SDK churn; Pipecat and telephony adapters are deferred. This sacrifices initial breadth for a working voice path.
2. Use one Python codebase for scenarios, execution, grading, and storage. Separate process lifecycles for the local API/runner are allowed, but avoid distributed microservices, Kafka, and Kubernetes. Bounded workers and explicit cancellation remain required.
3. Use hosted Supabase PostgreSQL for run metadata, results, and durable memory, superseding the initial SQLite proposal. Keep audio and detailed trace files local, finalized atomically and referenced by checksums. This reduces laptop service load but requires network access for persisted runs. Buffer/batch metadata writes away from audio-critical callbacks, preserve partial local artifacts on failure, and report synchronization errors. Offline fixture tests use isolated in-memory repositories. Keep privileged database credentials in backend configuration and enforce scoped access for shared data.
4. Separate fixture, text, recorded-audio, and duplex modes in both data and UI. More explicit coverage means less impressive headline numbers, but prevents invalid voice-quality claims.
5. Store normalized append-only events with schema versions, correlation IDs, local monotonic timing, and configuration snapshots. Keep vendor raw events in optional local artifacts. Normalization requires adapter maintenance but enables consistent comparisons.
6. Objective graders own state and timing results; optional LLM judges score semantic properties with evidence. Model judges introduce cost and variability, so never make them the sole pass/fail oracle.
7. Native fixture tools and structured memory first; MCP and semantic memory are optional follow-on integrations. This delays some fashionable technology in favor of verifying the actual failure cases.
8. No hosted application in this phase. Exported reports and a recorded demo provide portfolio access. Local usability does not establish production operation, scale, or external traction.

## Invariants

The user subsequently accepted live monitoring, predefined recovery, and post-call diagnosis. The core architecture includes an event monitor and agent-side recovery policy, with full scope in [live monitoring](../live-monitoring.md). Regression evaluation remains part of the product. The async tool monitor connects through the LiveKit voice adapter. A local React dashboard subscribes to report snapshots, presents evidence summaries and optional Groq hypotheses, and runs regression comparisons. Hosted Supabase metadata writes/read-back pass. Full microphone acceptance remains deferred.

- Test calls cannot mutate external production services. Tool fixtures have per-run namespaces and resettable state.
- Audio and detailed trace files stay local by default; selected metadata, results, and durable memory are stored in hosted Supabase. Cloud model runs also send the selected audio/text/context to their configured providers. Display the active data destinations before a run.
- Imported scenario data is validated data. Any executable Python test adapter is trusted developer code, registered locally; arbitrary imports and shell commands in uploaded scenarios are prohibited.
- Missing, partial, or incompatible measurements are explicit. A broken recorder, failed judge, or absent transcript cannot silently produce a passing result.
- Playback of saved events is a debugging view. Re-running a scenario executes an agent again; playback alone does not reproduce model behavior.
- Diagnostics make evidence-linked suggestions. Developers review changes to prompts, test assertions, and expected results.
- Live detection uses deterministic signals first. Diagnosis runs outside the audio-critical path and distinguishes observed errors from suspected causes.
- Recovery is allowlisted and bounded. An unknown write outcome must be reconciled or escalated, not blindly retried. Imported historical evidence cannot execute recovery actions.

## Revisit triggers

Add another framework after two external users demonstrate that adapter demand. Add team collaboration when shared-run use becomes a measured need; PostgreSQL is already selected through hosted Supabase. Add semantic retrieval when structured/text search fails reviewed cases. Add durable orchestration when diagnostic or approval jobs must survive restarts and span multiple steps beyond the runner's state machine.

## Validation

Fresh reference-suite executions now compare deliberately broken and corrected controllers, with independent grader and contract checks. A real Groq text tool-calling case and hosted metadata read-back pass. Audio timing against annotated recordings, full microphone acceptance, and external developer feedback remain pending; see [regression and pilot guide](../regression-and-pilot.md).
