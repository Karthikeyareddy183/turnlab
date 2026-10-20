# Regression and pilot guide

The remaining MVP implementation covers executable regression cases, bounded memory, run comparison, transcript scoring, and local failure recovery. Full microphone acceptance is intentionally deferred. This is a single-user developer pilot, not a production service or a completed external customer trial.

## Run it

From the repository root, start the dashboard with `./scripts/start-local.ps1`. The script uses the existing virtual environment and built frontend; it does not overwrite `.env` or install software. Open `http://127.0.0.1:8000` open **Testing** and expand **Check memory and booking safety**.

Choose **Broken memory (should fail)** and click **Run checks**, then choose **Working version (should pass)** and run again. **Before** and **After** fill in automatically with those two runs; click **Compare**. The comparison should show 0 newly broken, 4 fixed and 0 still failing. The duplicate-booking fault should produce one failed check. Both profiles execute code with new isolated state; they do not replay saved traces.

The versioned contract lives in `src/turnlab/regression.py`. Four cases exercise eight objective assertions: remembered date correction and booking arguments, user and tenant isolation, TTL expiry at its boundary, deletion, and idempotent duplicate booking. TTL tests advance a logical clock rather than waiting. Event offsets measure local execution time, not caller-perceived latency. The fingerprint includes inputs and expectations; comparisons reject changed contracts, missing/duplicate checks, different suite modes, and incomplete runs. It is a deterministic reference controller, not a model benchmark.

```powershell
.\.venv\Scripts\python.exe -m turnlab pilot-demo
.\.venv\Scripts\python.exe -m turnlab doctor
.\.venv\Scripts\python.exe -m turnlab regression --profile fault_memory
.\.venv\Scripts\python.exe -m turnlab regression --profile corrected
.\.venv\Scripts\python.exe -m turnlab compare .turnlab/runs/BASELINE_UUID.json .turnlab/runs/CANDIDATE_UUID.json
```

`pilot-demo` saves three fresh runs (two fault profiles and corrected code), checks both comparisons, and reports actual sample size. This proves detection of deliberately introduced reference faults, not that an arbitrary customer's bug is fixed. `regression` exits 1 for failed assertions; `compare` exits 1 for regressions or remaining candidate failures and 2 for invalid inputs/contracts. Passing results exit 0.

## Real model tool calls without a microphone

The optional **Run with Groq** button sends a fixed synthetic booking request to Groq. It executes the model's validated `remember_day` and `book_visit` calls against isolated scoped memory and an idempotent in-memory booking adapter. It checks remembering Thursday, correction to Friday, repeated booking requests, one committed booking, and the booked day. No external booking occurs. The model cannot select a filesystem path, a tenant, or executable code.

This path makes at most six provider requests and twelve tool calls, with no SDK retries and 1,200 maximum output tokens per request. It runs outside the API event loop and allows one text run at a time. Provider failure, output truncation, or exhausted budgets produces a persisted **incomplete** report, never a passing run. Model omission produces failed objective checks. Missing request-level failures do not establish conversational quality.

```powershell
# Optional dependencies if the voice extra is not installed:
.\.venv\Scripts\python.exe -m pip install -e ".[api,test,evaluation]"
# Explicit provider usage; uses the local .env Groq key and may consume credits:
.\.venv\Scripts\python.exe -m turnlab text-eval
```

Only completed runs of the same contract can be compared. Model name, request count, token usage, and elapsed execution time remain in the local report. Cost and audio latency are not inferred. One real Groq acceptance execution passed all five checks on this machine; a sample of one is not a reliability estimate.

## From incident to regression

Select a run with incidents or failed assertions and click **Create regression worksheet**. The downloadable local draft contains the source run ID, source fingerprint, incident/check references, and empty reproduction/expected-outcome fields. It requires review and cannot execute automatically. Review the evidence, define concrete inputs and expected outputs, implement a case in the versioned suite, and run both the broken and corrected adapter. Never convert the observed erroneous value into the expected answer merely to make a test pass.

## Recorded audio and transcript accuracy

The dashboard's transcript scorer compares a reference transcript to recognized text locally. English normalization applies Unicode NFKC, case folding, and punctuation-to-space conversion. Dynamic programming reports substitutions, deletions, insertions, and WER = total edits / reference words. WER can exceed 100%. Empty references, more than 2,000 words, and unvalidated language settings are rejected. There is no automatic quality threshold. Audio and transcripts are not included in hosted metadata.

```powershell
.\.venv\Scripts\python.exe -m turnlab score-transcript scenarios/audio/reference.txt scenarios/audio/hypothesis.txt
# Optional: explicitly uploads this single WAV to Deepgram, uses credits, then scores:
.\.venv\Scripts\python.exe -m turnlab transcribe-wav C:/path/to/recording.wav C:/path/to/reference.txt
```

The upload adapter accepts uncompressed mono/stereo WAV files up to 120 seconds and 10 MiB. It validates before upload and never scans a directory or records the microphone. The raw provider error body is not logged. This adapter has mocked upload/validation tests; actual recorded-file transcription through this new command remains an acceptance check. Scoring supplied text has passed browser and automated checks. TTS quality, non-English tokenization, automated duplex interruption timing, and end-to-end caller latency remain unmeasured.

## Reliability and support

Validated environment: Windows, Python 3.12, the committed dependency lockfiles, and the frontend package lock. Other operating systems have not been validated. Use Node 22 for frontend installation/build. `scripts/verify.ps1` runs backend tests, the TypeScript/production build, and the read-only local doctor. The Windows CI workflow repeats installation and checks without keys; its remote execution has not yet been observed.

Reports are saved with flush/fsync and atomic replacement. A failed replacement preserves the previous JSON. Partial `.tmp` files are ignored and counted by the doctor; corrupt/oversized JSON is excluded visibly. Artifact reads are capped at 8 MiB. Recorder disk failures increment a visible counter and do not terminate the tool session. A process kill can leave a stale active report; it is flagged, not rewritten to claim a successful close. Supabase outages retain local reports and retry later. Existing tests cover cancellation, deadlines, retry exhaustion, evidence eviction, session isolation, provider errors, and metadata exclusion.

`.env` is ignored and removed from Git tracking while preserved locally. This does not remove secrets from earlier Git history. Do not publish old credentials/history. API keys are backend-only; local reports/diagnoses/drafts are ignored. No audio is captured automatically. Retention is manual for this pilot: keep needed artifacts, then remove selected local copies yourself; there is no automatic deletion job. Bind only to loopback, because shared authentication and multi-user authorization are outside this local MVP.

Supabase authenticated read and table access passed, and the running backend successfully upserted selected metadata. A read-back of the synthetic model run verifies hosted persistence. Raw traces, transcripts, tool arguments/results, and audio stay local. Synchronization uploads at most the latest 100 reports in each scan; this is not a durable unlimited backfill queue. Upload receipts suppress unchanged snapshots. After restarting, an up-to-date receipt alone is not a new authentication check; new writes revalidate access.

Before calling the pilot validated for voice: complete the microphone acceptance in `voice-quickstart.md`, inspect a live incident in the dashboard, and measure accuracy/latency on a declared dataset. External developer feedback remains outstanding; no production-load or job-market performance claims are established by these tests.
