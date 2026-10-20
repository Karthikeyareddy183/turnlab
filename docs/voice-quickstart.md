# Local voice integration

Phase 2 code is implemented and tested against LiveKit Agents 1.8.8. Local worker registration and Groq/Deepgram credential smoke checks have passed, including a short synthesis/transcription round trip. A full spoken microphone conversation has not yet been verified.

## Setup

Keep the local media server running in its existing PowerShell window. In another PowerShell window, from `D:\conversational_AI_Agent`:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[api,voice,test]"
```

For a fresh environment, create `.venv` first with Python 3.11 or later. `requirements-voice.lock` records the full dependency set installed on Python 3.12/Windows; install that file before the editable project to reproduce those versions.

Add valid `GROQ_API_KEY` and `DEEPGRAM_API_KEY` values to the private `.env`. Empty values and known template placeholders are rejected. Do not copy `.env.example` over an existing `.env` containing credentials. No ElevenLabs key or LiveKit Cloud account is required for this profile.

Connection defaults are explicit: `ws://127.0.0.1:7880`, `devkey`, and `secret`. These match `livekit-server.exe --dev`. Existing standard `LIVEKIT_*` values in `.env` are overridden in the worker process by the explicit `TURNLAB_LIVEKIT_*` local settings; the file itself is unchanged. Non-loopback `TURNLAB_LIVEKIT_URL` values are rejected.

Check readiness without provider requests:

```powershell
.\.venv\Scripts\python.exe -m turnlab voice-check
```

This checks TCP reachability and whether non-placeholder keys are present, not whether those keys authenticate successfully. It prints no credential values. Exit 0 means ready to attempt a call; exit 2 means configuration or connectivity is incomplete.

## First conversation

Run the console voice client, allowing it to use your microphone/speaker:

```powershell
.\.venv\Scripts\python.exe agent.py console
```

Console mode is the local microphone test path. To register the worker for room-based browser/client calls instead:

```powershell
.\.venv\Scripts\python.exe agent.py dev
```

Room mode needs a separate voice client connected to the local LiveKit room; a browser voice caller is not implemented yet. The React monitoring dashboard inspects reports and does not join as a caller. Merely starting the media server and worker does not create a caller. Do not run multiple reference workers for the same test at once. Provider-backed calls consume configured provider usage.

## Demonstrate a recovery incident

Stop an existing worker, then enable isolated fault fixtures in the same terminal:

```powershell
$env:TURNLAB_DEMO_FAULTS = "true"
.\.venv\Scripts\python.exe agent.py console
```

Say “What is the status of ticket DEMO-001?” The fixture lookup fails once with a transient connection error, then succeeds through one allowed retry. Say “Run the booking timeout demonstration.” One fixture write commits and loses its acknowledgement. The monitor records an uncertain outcome and requests review without retrying it. Repeated calls to that demonstration in the same session do not create another fixture booking. No real booking or human transfer occurs.

Fault injection is off by default. After testing, stop the worker and set `$env:TURNLAB_DEMO_FAULTS = "false"`.

## Inspect the evidence

The worker logs a `report_id` and concise incident notifications. `.turnlab/runs/<report_id>.json` is updated approximately once per second and flushed during normal shutdown. The same file is readable through the local API's `GET /api/runs/{uuid}` endpoint.

Captured evidence includes instrumented tool attempts/recovery, bounded session states, provider error types, and close reason. Exception messages, raw provider objects, transcripts, and audio are not saved by this implementation. Missing audio-quality measurements are not inferred from tool timings. Evidence eviction and persistence failures are visible in report metadata. An abrupt process kill may leave a report marked active; normal shutdown flush is tested, crash reconciliation is deferred.

The session recorder does disk writes in a background thread; audio callbacks only append selected metadata. SDK-provider errors are observed, not automatically diagnosed or fixed by a second provider. A real provider fallback needs a separately configured and tested implementation.

Baseline models are configurable: Groq `openai/gpt-oss-20b`, Deepgram `nova-3` in English, and `aura-2-thalia-en`. Local Silero VAD handles turns/interruption; Cloud noise cancellation and Cloud interruption models are not enabled. These choices have not yet been compared in a live-call benchmark.

## Validation status

The integration suite covers actual SDK plugin constructors/event hooks with dummy credentials, local-profile CLI override, fault isolation, duplicate prevention, failed-startup report preservation, and recording failures. Silero loading, local worker registration, and provider API credentials have passed separate smoke checks. None establishes full-conversation accuracy or latency. The [React inspector and optional diagnosis](dashboard.md), hosted metadata synchronization, [regression comparisons and transcript scoring](regression-and-pilot.md) are implemented. Full microphone acceptance remains deferred.
