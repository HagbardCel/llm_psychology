# Phase 8C Outcome

Live operator result for overlapping complete `simulate-local-llm` journeys
against serial MTPLX 2.8.1. Protocol: [`evals/phase8c/README.md`](README.md).

**Status:** Stage 1 closed **inconclusive** after a genuine C1 workload
failure. The remaining C4 run was cancelled; no Stage 2 confirmation was run.
Protocol amended: 2026-08-19.
Phase 8C contract: Stage 1 (short C1/C2/C4) → conditional Stage 2 confirmation pair → stop.
Long Stage 3/4 benchmarks were removed from Phase 8C.

Do not change the CLI default (`--concurrency 1`). Do not compare walls to
Phase 8B.

## Source revisions (protocol vs benchmarks)

- Protocol revision/date: `2026-08-19`
- Stage 1 benchmark source revision: `2eab7d8debb6bcee811a61e90c1a8e3619e61153`
  (runtime source; timed rows recorded this revision)
- Stage 2 benchmark source revision: N/A (Stage 2 not executed)

## Fixture

| Item | Value |
|---|---|
| Source revision | `2eab7d8debb6bcee811a61e90c1a8e3619e61153` (merge of PR #69) |
| Working tree | clean |
| Model | `Youssofal/Qwen3.8-27B-MTPLX-Optimized-Speed` (`mtplx-qwen38-27b-optimized-speed`) |
| MTPLX | **2.8.1** (`venv-2.8.1`; metadata 2.8.1; CLI `mtplx 2.8.0 (2.8.1)`) |
| llguidance | 1.8.0 |
| PyPI current at install | 2.8.1 (no freshness override) |
| Scheduler | serial, `--ssd-session-cache off`, `--reasoning-effort low` |
| Request extras | `enable_thinking=true`, `reasoning_effort=low`, `top_p=0.95`, `top_k=20` |
| Style | explicit `jung` |
| Task timeouts | `JUNG_LLM_TASK_CONFIG_JSON` `timeout_seconds=600` on all six tasks (recorded; product default is 120s) |
| Simulation CLI | `--patient-timeout 600 --workflow-timeout 1800` |

Session, supervisor, and patient all used `http://127.0.0.1:8000/v1` and the
same model. Structured modes remained default (`json_schema` for
`intake_patch` / `assessment` / `post_session_*`).

## Preflight

`make smoke-local-llm` with the extras above: **3 passed** (174.58s, then a
repeat 107.82s).

Wiring in child `run.json` matched the fixture (endpoints, models, structured
modes, clean `2eab7d8`). Journeys did **not** reach style selection.

| Row | Concurrency | Result |
|---|---|---|
| `preflight-c2` | 2 | both failed: `chat_llm_timeout` @120s / `chat_invalid_llm_output` |
| `preflight-c2-timeout600` | 2 | both failed: `chat_llm_timeout` @600s on `intake_patch` |
| `preflight-s1` | 1 | failed: `chat_invalid_llm_output` after intake_patch initial+correction |
| `preflight-s1-20260817T163604Z` | 1 | same `chat_invalid_llm_output` |

Serial failures: `IntakeRecordPatch` semantic validation
`unknown/unable intake evidence requires direct_ask=True` on
`presenting_problem.main_concern`, symptoms, and time_course fields. One
correction attempt did not clear it.

Concurrent C=2 on a clean-enough server still burned the full 600s client
timeout on `intake_patch`. The MTPLX log showed short thinking completions
(~14–21s) then silence until the client timed out.

## Stage 1 evidence

| Row | Status | Suite wall | Mechanical validity / result |
|---|---|---:|---|
| C1 (`--concurrency 1`) | failed | 6030.60s | genuine workload failure: child timeout and patient-generation failures |
| C2 (`--concurrency 2`) | complete | 7427.88s | invalid for timing selection: `git_worktree_dirty=true`; otherwise all 4 children complete and observed concurrency reached 2 |
| C4 (`--concurrency 4`) | cancelled | N/A | cancelled after the genuine C1 failure closed Stage 1 |

The C1 failure is a counted workload failure, not an externally invalidated
observation. Under the amended contract, it closes Phase 8C as inconclusive:
there is no valid serial control for a speedup comparison. C4 was not allowed
to continue after that closure decision.

## Selection

No concurrency recommendation. Retain `--concurrency 1`.
Stop reason: C1 had a genuine workload failure, so no Stage 1 speedup
comparison was possible. No Stage 2 confirmation was authorized.

This is not a measured speedup result or ceiling. The C1 fixture did not
complete successfully, C2 was mechanically invalid because the worktree was
dirty, and C4 was cancelled after the contract-required closure.

## Stage 1 decision

- stage1_C1_wall: `6030.596786` (failed; not eligible for speedup)
- stage1_candidate_wall: N/A (no mechanically valid candidate)
- stage1_speedup: N/A
- candidate selection: N/A
- Stage 1 decision outcome: close inconclusive because C1 had a genuine workload failure.

## Stage 2 confirmation

Not executed.

Stage 2 statistics framing (template contract):

- one suite observation per arm (`n=1` suites)
- each suite contains four independent journey replicas (`4` child runs)

Stage 2 timing fields (only populated if Stage 2 is executed and mechanically valid):

- stage2_C1_wall: N/A
- stage2_candidate_wall: N/A
- stage2_speedup: N/A
- deterministic execution order used (candidate→C1 or C1→candidate): N/A
- Stage 2 decision outcome: not executed (Stage 1 closed inconclusive after the C1 workload failure).

## Retry / invalidation accounting (template contract)

- no automatic retries
- at most one documented replacement attempt per externally invalidated observation

## Evidence

Gitignored operator workspace:

```text
logs/evals/phase8c/   worksheet, resolved env, smoke log, row directories
```
