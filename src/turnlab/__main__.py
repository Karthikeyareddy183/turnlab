"""CLI for explicit offline fixture evaluation."""

import argparse
import asyncio
import json
from pathlib import Path
import sys

from turnlab.core import ContractError, Scenario, grade
from turnlab.storage import ReportStore
from turnlab.monitoring import run_monitor_demo


def main() -> int:
    parser = argparse.ArgumentParser(description="TurnLab offline fixture evaluator (no live voice execution)")
    subcommands = parser.add_subparsers(dest="command", required=True)
    run = subcommands.add_parser("run", help="grade a JSON fixture scenario")
    run.add_argument("scenario", type=Path)
    run.add_argument("--output", type=Path, default=Path(".turnlab/runs"))
    demo = subcommands.add_parser("monitor-demo", help="exercise safe read retry and an uncertain write with async fixture tools")
    demo.add_argument("--output", type=Path, default=Path(".turnlab/runs"))
    subcommands.add_parser("voice-check", help="check local server and key configuration without inference requests")
    suite = subcommands.add_parser("regression", help="execute isolated reference memory/tool regression cases")
    suite.add_argument("--profile", choices=["corrected", "fault_memory", "fault_duplicate_booking"], default="corrected")
    suite.add_argument("--output", type=Path, default=Path(".turnlab/runs"))
    compare = subcommands.add_parser("compare", help="compare two saved executable reference-suite reports")
    compare.add_argument("baseline", type=Path)
    compare.add_argument("candidate", type=Path)
    score = subcommands.add_parser("score-transcript", help="score supplied English reference/hypothesis text files locally")
    score.add_argument("reference", type=Path)
    score.add_argument("hypothesis", type=Path)
    score.add_argument("--output", type=Path, default=Path(".turnlab/runs"))
    audio = subcommands.add_parser("transcribe-wav", help="explicitly send one WAV to Deepgram (API credits), then score it")
    audio.add_argument("audio", type=Path)
    audio.add_argument("reference", type=Path)
    audio.add_argument("--output", type=Path, default=Path(".turnlab/runs"))
    subcommands.add_parser("doctor", help="inspect local installation and artifacts without cloud requests")
    text_run = subcommands.add_parser("text-eval", help="explicitly run a synthetic Groq text tool-calling case (API credits)")
    text_run.add_argument("--output", type=Path, default=Path(".turnlab/runs"))
    subcommands.add_parser("pilot-demo", help="execute failing profiles and corrected code, save evidence and compare; no cloud calls")
    args = parser.parse_args()
    try:
        if args.command == "voice-check":
            from turnlab.preflight import check_voice_environment

            readiness = check_voice_environment()
            print(json.dumps(readiness))
            return 0 if readiness["ready_for_voice_test"] else 2
        if args.command == "doctor":
            from turnlab.reliability import doctor
            print(json.dumps(doctor(Path.cwd()), indent=2))
            return 0
        if args.command == "pilot-demo":
            from turnlab.reliability import pilot_demo
            result = pilot_demo(Path(".turnlab/runs"))
            print(json.dumps(result, indent=2))
            return 0 if result["verified"] else 1
        if args.command == "compare":
            from turnlab.regression import compare_runs
            result = compare_runs(json.loads(args.baseline.read_text(encoding="utf-8")), json.loads(args.candidate.read_text(encoding="utf-8")))
            print(json.dumps(result, indent=2))
            return 1 if result["regressions"] or result["remaining_failures"] else 0
        if args.command == 'text-eval':
            from dotenv import dotenv_values
            from turnlab.text_agent import GroqTextRunner
            env = dotenv_values('.env')
            key = env.get('GROQ_API_KEY') or ''
            if not key.strip():
                raise ValueError('Groq text evaluation is not configured')
            report = GroqTextRunner(key, env.get('TURNLAB_LLM_MODEL') or 'openai/gpt-oss-20b').run()
        elif args.command == "regression":
            from turnlab.regression import run_suite
            report = run_suite(args.profile)
        elif args.command in {"score-transcript", "transcribe-wav"}:
            from turnlab.audio import score_transcript, transcribe_wav, words
            reference = args.reference.read_text(encoding="utf-8")
            if args.command == "transcribe-wav":
                if not words(reference):
                    raise ValueError('Reference must contain at least one word before uploading audio')
                from dotenv import dotenv_values
                hypothesis = transcribe_wav(args.audio, dotenv_values('.env').get('DEEPGRAM_API_KEY') or '')
            else:
                hypothesis = args.hypothesis.read_text(encoding="utf-8")
            report = score_transcript(reference, hypothesis)
        else:
            report = asyncio.run(run_monitor_demo()) if args.command == "monitor-demo" else grade(Scenario.load(args.scenario))
        target = ReportStore(args.output).save(report)
    except (ContractError, OSError, ValueError) as exc:
        print(f"turnlab: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"status": report["status"], "mode": report["mode"], "report": str(target)}))
    return 0 if report["status"] in {"passed", "completed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
