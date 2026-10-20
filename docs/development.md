# Running the foundation locally

Implemented: fixture grading, async tool recovery, LiveKit reference adapter, React inspector/live updates, evidence summaries, optional Groq hypotheses, executable reference and Groq text regressions, scoped memory lifecycle checks, run comparisons, review worksheets, and English transcript scoring. Hosted Supabase metadata writes/read-back pass. A full microphone conversation remains deferred. See [regression and pilot guide](regression-and-pilot.md), [dashboard guide](dashboard.md), [build phases](build-phases.md), and [voice quickstart](voice-quickstart.md).

Python 3.11 or later is required. From the repository root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[api,test]"
.\.venv\Scripts\python.exe -m turnlab run scenarios/booking-correct.json
.\.venv\Scripts\python.exe -m turnlab run scenarios/duplicate-booking.json
.\.venv\Scripts\python.exe -m turnlab monitor-demo
```

The first scenario passes. The second intentionally fails: its supplied final state contains two bookings. Exit codes are 0 for pass, 1 for a failed assertion, and 2 for invalid input or a persistence error. Reports are written atomically to `.turnlab/runs/`; missing speech measurements are explicitly `not_measured`.

`monitor-demo` executes two isolated async operations. A read fails once and recovers through one allowed retry. A write commits and then reports a timeout; it is not retried, and the result is `uncertain` with a human-review request. The demo exits 0 when execution completes; that exit code does not mean every operation succeeded. Read `operations` and `incidents` in the report. No actual human transfer, provider call, or voice session occurs.

Start the local API from the repository root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn turnlab.api:local_app --factory --host 127.0.0.1 --port 8000
```

The OpenAPI explorer is at `http://127.0.0.1:8000/docs`. Endpoints:

- `GET /api/health`: reports implemented mode and connection status.
- `GET /api/scenarios`: lists registered JSON fixtures.
- `POST /api/runs` with `{"scenario_id":"booking-correct"}`: grades the fixture and stores a local report.
- `GET /api/runs/{uuid}`: returns a stored report.
- `POST /api/demos/tool-monitor`: executes only the built-in isolated recovery demo and stores its report.
- `GET /api/runs`: recent local run summaries and skipped-report count.
- `GET /api/events`: server-sent snapshot updates for the inspector.
- `GET /api/runs/{uuid}/analysis`: deterministic observations and investigation suggestions.
- `GET /api/runs/{uuid}/export`: download the local report.
- `GET /api/runs/{uuid}/diagnosis`: last optional model diagnosis and stale-evidence status.
- `POST /api/runs/{uuid}/diagnosis`: explicitly request optional Groq hypotheses; may consume credits.
- `POST /api/regressions/run`: execute a built-in isolated reference profile.
- `POST /api/regressions/text`: explicitly execute the bounded synthetic Groq tool-calling case; may consume credits.
- `POST /api/regressions/compare`: compare completed baseline/candidate IDs with matching evaluation contracts.
- `POST /api/runs/{uuid}/regression-draft`: save a review-required worksheet; never executes automatically.
- `GET /api/regression-drafts/{uuid}/export`: download that worksheet.
- `POST /api/audio/score`: score supplied English reference/hypothesis text locally.

Only scenarios registered from the repository's `scenarios/` directory are executable through the API. A JSON fixture cannot specify Python imports, commands, or file paths to execute. Bind this unauthenticated development API to loopback only; authentication will be required before any shared access.

Run checks:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Phase 1 verification: 20 tests passed on the project's Windows/Python 3.12 environment, covering grading, API validation, report persistence, safe/unsafe retry behavior, shared retry limits, cancellation, deadlines, and bounded evidence. These are local tool/fixture results, not voice-provider benchmarks.

`agent.py` now launches `turnlab.voice`, the local monitored reference agent. `requirements.txt` installs the package with API/voice extras. Groq LLM and Deepgram STT/TTS replace the prototype providers. No API keys are required for fixture grading or `monitor-demo`; voice calls need both provider keys.

Selected architecture: local LiveKit, Groq LLM, Deepgram STT/TTS, hosted Supabase metadata, FastAPI backend, and React/TypeScript dashboard. Reports and diagnoses stay local until Supabase metadata sync is explicitly configured. Starting a voice conversation invokes the configured providers. Automated integration tests use dummy keys and mock provider requests.
