# Dashboard and optional hosted persistence

The React/TypeScript inspector displays local run reports, live incident updates, evidence timelines, scenario assertions, JSON exports, and evidence-first analysis. An optional Groq action produces explicitly unverified hypotheses. It does not change code, prompts, or agent state.

Hosted Supabase is configured in the user's local environment, and metadata writes/read-back have passed. New installations can use local reports without configuring Supabase.

## Run the dashboard

From the repository root, build the frontend once:

```powershell
Set-Location web
npm.cmd ci
npm.cmd run build
Set-Location ..
.\.venv\Scripts\python.exe -m uvicorn turnlab.api:local_app --factory --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. FastAPI serves `web/dist` when it exists. Rebuild after frontend changes and restart the API after backend changes. The production build needs only the API process at runtime; there is no hosted frontend.

For frontend development, keep the API on port 8000 and run `npm.cmd run dev` from `web/` in another terminal. Vite serves port 5173 and proxies `/api` to the local backend. No Supabase or Groq secrets belong in the frontend environment or bundle.

## Test without a voice call

Open **Testing**, then **Run demo**. It executes isolated async callbacks, creates a report, and selects it in the test list. It does not make a customer call or spend API credits. **Check memory and booking safety** contains the regression suite, run comparison and speech-to-text accuracy scoring; **Grade a saved example conversation** contains fixture grading. Deliberately broken fixtures are expected to fail. Tests never appear in the Calls list.

The dashboard counts only the most recent 100 local reports. It labels voice sessions separately from supplied fixtures and async tool executions. It does not invent audio latency, speech accuracy, or call-success metrics.

## Observe a voice session

Run the reference agent using the [voice quickstart](voice-quickstart.md). Its periodic reports appear automatically through `/api/events`, even when the worker runs in a separate process. The feed sends current snapshots on reconnect, not a guarantee that every intermediate event was delivered. Raw local reports remain the evidence source.

**Dashboard online** (header) means the dashboard is connected to FastAPI. It does not mean a caller is connected. Sessions without a recent report update show **Updates stopped**; an abrupt process crash does not establish a clean call completion. Dropped evidence and failed report reads remain visible.

## Inspect and investigate

- **Calls:** the default page. Choose a call to see its summary (duration, caller turns, agent replies, tool calls and retries, longest thinking pause), a strip showing what the agent was doing over time, and its issues. Counts come from captured events; if early events were evicted the page says the counts may be low.
- **What happened?:** expand an individual issue for observations and suggested checks. No automatic root-cause claim is made.
- **Technical details:** collapsed by default. Contains Events, Test results, Raw report, report download, and test worksheet creation. Event offsets are not caller-perceived latency.
- **Testing:** demos, regression comparison, model tool evaluations, supplied-transcript scoring, and saved scenarios.

**Suggest causes** is opt-in per run. The adjacent helper text explains that it sends selected incident metadata to Groq and may consume credits. It excludes raw transcripts, audio, tool arguments/results, and exception messages. Supplied event IDs and finding IDs are validated in the response; invalid references fail visibly. Possible explanations remain unverified even when they cite valid evidence. Diagnosis files are saved locally in `.turnlab/diagnoses`; changed report evidence marks an earlier diagnosis stale. No investigation action is executed.

The button requires a valid configured `GROQ_API_KEY` and the OpenAI-compatible client supplied by the voice extra. Install `.[api,voice,test]` for the full current feature set. Offline evidence summaries work without it.

## Connect Supabase later

1. Open your own Supabase project's SQL editor and review/run [the migration](../supabase/migrations/202610150001_turnlab_runs.sql).
2. Set `SUPABASE_URL` and `SUPABASE_SECRET_KEY` in the private root `.env`. Use the backend `sb_secret_...` key, not a publishable browser key. Set `TURNLAB_WORKSPACE` if sharing a project across local workspaces.
3. Restart FastAPI. The dashboard footer and `/api/health` show configuration, last upload, and errors.

No schema is applied automatically. The first configured API run uploads selected metadata from the latest local reports. Keep this in mind before enabling it against a project containing sensitive test data. The application is a single-user local developer tool, not a shared authenticated service.

The `turnlab_runs` table stores run IDs, modes/status, timestamps, selected incident metadata, assertion outcomes, telemetry counters, and a local artifact identifier. It excludes detailed event streams, raw arguments/results, transcripts, audio, and absolute file paths. Privileged credentials remain backend-only. RLS is enabled, browser roles have no table access, and only the server role is granted data access. This does not implement multi-user application authorization.

Synchronization runs in the API process every five seconds, away from voice callbacks. The local report is saved first. Failed uploads retain the report and retry later; local upload receipts avoid resending an unchanged snapshot. A SQL trigger prevents older snapshots from replacing newer records. Errors contain a status code or fixed message rather than raw provider response bodies. A configured-but-unused connection is not reported as authenticated.

## Current verification

The frontend TypeScript/production build passes. Backend tests cover catalog integrity, stale runs, streaming/reconnect, evidence summaries, metadata exclusion, upload receipts, sync outage recovery, diagnosis validation, stale hypotheses, regressions, memory lifecycle, transcript scoring, and disk recovery. Real Groq diagnosis and text tool-calling tests pass, and a synthetic model run was read back from hosted Supabase. Browser checks cover fixture/suite execution, run comparison, scoring, worksheets, incident navigation, cross-process updates, and responsive layouts. Full microphone acceptance remains deferred. See [regression and pilot guide](regression-and-pilot.md).
