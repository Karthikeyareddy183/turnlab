"""Local dashboard API; never accepts arbitrary filesystem paths or executable scenarios."""

import asyncio
from contextlib import asynccontextmanager
import os
import json
from hashlib import sha256
from datetime import datetime, timezone
import importlib.util
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from turnlab.core import ContractError, Scenario, grade
from turnlab.storage import ReportStore
from turnlab.monitoring import run_monitor_demo
from turnlab.analysis import analyze_report
from turnlab.streaming import stream_reports
from turnlab.synchronization import SupabaseSync, SyncSettings
from turnlab.diagnosis import DiagnosisError, GroqDiagnoser
from turnlab.regression import run_suite, compare_runs, incident_draft, PROFILES
from turnlab.audio import score_transcript
from turnlab.text_agent import GroqTextRunner


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str


class SuiteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: str = "corrected"


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    baseline_id: UUID
    candidate_id: UUID


class TranscriptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference: str = Field(min_length=1, max_length=20000)
    hypothesis: str = Field(max_length=20000)
    language: str = "en"


def create_app(scenario_dir: Path, artifact_dir: Path, *, sync_settings: SyncSettings | None = None,
               sync_configuration_error: str | None = None, diagnoser: GroqDiagnoser | None = None) -> FastAPI:
    store = ReportStore(artifact_dir)
    synchronizer = SupabaseSync(store, sync_settings)
    diagnoses = ReportStore(artifact_dir.parent / "diagnoses")
    drafts = ReportStore(artifact_dir.parent / "drafts")
    diagnosis_lock = asyncio.Lock()
    text_lock = asyncio.Lock()

    def report_fingerprint(report):
        return sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(synchronizer.run()) if sync_settings else None
        try:
            yield
        finally:
            synchronizer.stop()
            if task:
                await task

    app = FastAPI(title="TurnLab local monitoring API", version="0.2.0", lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "test", "testserver"])
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
    @app.middleware("http")
    async def restrict_browser_origins(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and origin not in {"http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:8000", "http://127.0.0.1:8000"}:
            return JSONResponse({"detail": "Origin is not allowed"}, status_code=403)
        return await call_next(request)
    scenarios: dict[str, Scenario] = {}
    for path in sorted(scenario_dir.glob("*.json")):
        scenario = Scenario.load(path)
        if scenario.id in scenarios:
            raise ContractError(f"duplicate scenario id: {scenario.id}")
        scenarios[scenario.id] = scenario

    @app.get("/api/health")
    def health():
        sync = synchronizer.status()
        if sync_configuration_error:
            sync.update(state="configuration_error", last_error=sync_configuration_error)
        return {"status": "ok", "mode": "local_monitoring",
                "supabase_connected": sync["last_success"] is not None and sync["state"] != "error", "synchronization": sync,
                "diagnosis_available": diagnoser is not None, "text_evaluation_available": diagnoser is not None}

    @app.get("/api/runs")
    def list_runs():
        return store.summaries()

    @app.get("/api/events")
    async def events(request: Request):
        return StreamingResponse(stream_reports(store, request.is_disconnected), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    def read_report(run_id: UUID):
        try:
            return store.get(str(run_id))
        except FileNotFoundError as exc:
            raise HTTPException(404, "Unknown run") from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(503, "Report is unavailable or invalid") from exc

    @app.post("/api/regressions/run", status_code=201)
    def execute_suite(request: SuiteRequest):
        if request.profile not in PROFILES:
            raise HTTPException(422, "Unknown reference profile")
        report = run_suite(request.profile)
        try:
            store.save(report)
        except OSError as exc:
            raise HTTPException(503, "Could not persist the regression report") from exc
        return report

    @app.post("/api/regressions/compare")
    def compare(request: CompareRequest):
        try:
            return compare_runs(read_report(request.baseline_id), read_report(request.candidate_id))
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(422, "Comparison needs completed runs of the same suite with matching contracts, checks, and expectations") from exc

    @app.post("/api/regressions/text", status_code=201)
    async def execute_text_case():
        if diagnoser is None:
            raise HTTPException(503, "Groq text evaluation is not configured")
        if text_lock.locked():
            raise HTTPException(409, "A text evaluation is already running")
        async with text_lock:
            report = await asyncio.to_thread(GroqTextRunner(diagnoser.key, diagnoser.model).run)
            try:
                await asyncio.to_thread(store.save, report)
            except OSError as exc:
                raise HTTPException(503, "Could not save text evaluation") from exc
            return report

    @app.post("/api/runs/{run_id}/regression-draft", status_code=201)
    def draft(run_id: UUID):
        report = read_report(run_id)
        if not report.get("incidents") and not any(c.get("passed") is False for c in report.get("checks", [])):
            raise HTTPException(422, "Select a run with incidents or failed checks")
        result = incident_draft(report)
        try:
            drafts.save(result)
        except OSError as exc:
            raise HTTPException(503, "Could not save the regression worksheet") from exc
        return result

    @app.get("/api/regression-drafts/{draft_id}/export")
    def export_draft(draft_id: UUID):
        try:
            result = drafts.get(str(draft_id))
        except FileNotFoundError as exc:
            raise HTTPException(404, "Unknown worksheet") from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(503, "Worksheet is unavailable") from exc
        return JSONResponse(result, headers={"Content-Disposition": f'attachment; filename="turnlab-draft-{draft_id}.json"'})

    @app.post("/api/audio/score", status_code=201)
    def score_audio(request: TranscriptRequest):
        try:
            report = score_transcript(request.reference, request.hypothesis, language=request.language)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        try:
            store.save(report)
        except OSError as exc:
            raise HTTPException(503, "Could not save transcript score") from exc
        return report

    @app.get("/api/runs/{run_id}/analysis")
    def analysis(run_id: UUID):
        return analyze_report(read_report(run_id))

    @app.get("/api/runs/{run_id}/diagnosis")
    def get_diagnosis(run_id: UUID):
        report = read_report(run_id)
        try:
            diagnosis = diagnoses.get(str(run_id))
        except FileNotFoundError:
            return {"state": "not_requested", "run_id": str(run_id)}
        except (OSError, ValueError) as exc:
            raise HTTPException(503, "Stored diagnosis is unavailable") from exc
        return {**diagnosis, "state": "available", "stale": diagnosis["evidence_fingerprint"] != report_fingerprint(report)}

    @app.post("/api/runs/{run_id}/diagnosis")
    async def diagnose(run_id: UUID):
        if diagnoser is None:
            raise HTTPException(503, "Groq diagnosis is not configured")
        if diagnosis_lock.locked():
            raise HTTPException(409, "Another diagnosis is running; retry after it finishes")
        async with diagnosis_lock:
            report = await asyncio.to_thread(read_report, run_id)
            try:
                result = await asyncio.to_thread(diagnoser.diagnose, report)
            except DiagnosisError as exc:
                raise HTTPException(502, str(exc)) from exc
            diagnosis = {"id": str(run_id), "run_id": str(run_id), "method": "groq_hypotheses",
                         "created_at": datetime.now(timezone.utc).isoformat(), "evidence_fingerprint": report_fingerprint(report), **result}
            try:
                await asyncio.to_thread(diagnoses.save, diagnosis)
            except OSError as exc:
                raise HTTPException(503, "Diagnosis completed but could not be saved locally") from exc
            latest = await asyncio.to_thread(read_report, run_id)
            return {**diagnosis, "state": "available", "stale": report_fingerprint(latest) != diagnosis["evidence_fingerprint"]}

    @app.get("/api/runs/{run_id}/export")
    def export(run_id: UUID):
        return JSONResponse(read_report(run_id), headers={"Content-Disposition": f'attachment; filename="turnlab-{run_id}.json"'})

    @app.get("/api/scenarios")
    def list_scenarios():
        return [{"id": s.id, "name": s.name, "mode": "fixture"} for s in scenarios.values()]

    @app.post("/api/demos/tool-monitor", status_code=201)
    async def tool_monitor_demo():
        # Only built-in, isolated callbacks run here. No user-selected tool code.
        report = await run_monitor_demo()
        try:
            await asyncio.to_thread(store.save, report)
        except OSError as exc:
            raise HTTPException(503, "Could not persist the local report") from exc
        return report

    @app.post("/api/runs", status_code=201)
    def run_fixture(request: RunRequest):
        scenario = scenarios.get(request.scenario_id)
        if scenario is None:
            raise HTTPException(404, "Unknown scenario")
        report = grade(scenario)
        try:
            store.save(report)
        except OSError as exc:
            raise HTTPException(503, "Could not persist the local report") from exc
        return report

    @app.get("/api/runs/{run_id}")
    def get_run(run_id: UUID):
        return read_report(run_id)

    built_dashboard = scenario_dir.parent / "web" / "dist"
    if built_dashboard.is_dir():
        app.mount("/", StaticFiles(directory=built_dashboard, html=True), name="dashboard")
    return app


def local_app() -> FastAPI:
    """Invoke from the repository root using uvicorn's --factory flag."""
    from dotenv import load_dotenv

    load_dotenv()
    root = Path.cwd()
    scenario_dir = root / "scenarios"
    if not scenario_dir.is_dir():
        raise RuntimeError("Run from the repository root containing scenarios/")
    try:
        sync_settings, configuration_error = SyncSettings.from_env(os.environ), None
    except ValueError as exc:
        sync_settings, configuration_error = None, str(exc)
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    diagnoser = GroqDiagnoser(groq_key, os.getenv("TURNLAB_LLM_MODEL", "openai/gpt-oss-20b")) if groq_key and not groq_key.lower().startswith(("your_", "replace_")) and importlib.util.find_spec("openai") else None
    return create_app(scenario_dir, root / ".turnlab" / "runs", sync_settings=sync_settings,
                      sync_configuration_error=configuration_error, diagnoser=diagnoser)
