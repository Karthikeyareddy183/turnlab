# Local acceptance results

Recorded 2026-10-15 on Windows / Python 3.12. These results describe this development machine and synthetic cases, not a production reliability benchmark.

| Check | Result | Sample / boundary |
| --- | --- | --- |
| Automated backend suite | 58 tests passed | Includes mocked cloud failures; no microphone calls |
| TypeScript and production frontend build | Passed | Local installed dependency lock |
| Dependency consistency | Passed | `pip check` |
| Executable offline pilot | Passed | Three fresh runs, four cases and eight assertions per run |
| Memory fault vs corrected reference | Four fixes, zero remaining failures | Synthetic fault profile; logical TTL clock |
| Duplicate booking fault vs corrected reference | One fix, zero remaining failures | Isolated booking adapter |
| Real Groq text tool evaluation | All five checks passed | One run; synthetic inputs; not a reliability estimate |
| Hosted Supabase persistence | Upsert and read-back passed | Synthetic Groq run metadata; no raw traces/transcripts uploaded |
| Dashboard workflow | Passed | Suite execution, comparison, worksheet creation, transcript scoring |
| Transcript scorer known error | 20% WER | One substitution in five words; supplied text, no STT execution |
| Recorded WAV adapter | Validation/upload/error tests passed with mocks | Actual file-upload acceptance remains pending |
| Full microphone conversation | Deferred by user | Accuracy, interruption and caller-perceived latency unmeasured |
| GitHub Actions execution | Not run remotely | Workflow prepared |
| External developer pilot feedback | Not collected | Required before wider pilot claims |

The dashboard and CLI save full evidence locally. The regression worksheet requires a developer to define reproduction steps and expectations before creating an executable case. No automatic fix or production-scale validation is claimed.
