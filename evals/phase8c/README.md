# Phase 8C — parallel independent longitudinal simulations

Experiment contract for overlapping complete `simulate-local-llm` journeys.
Write `OUTCOME.md` in this directory only after the live benchmark; do not
create that file until measurements exist.

Raw machine evidence stays under gitignored `logs/simulations/` (and any
operator worksheet under `logs/evals/phase8c/`).

Jung remains backend-neutral. This directory does **not** start, stop, or
configure MTPLX. Server lifecycle below is operator protocol.

## What 8C measures

Phase 8B's M4 row showed outstanding-request overlap on a **serial** MTPLX
scheduler, not server-side parallel inference. Phase 8C asks:

> How much wall-clock time can we save by overlapping independent
> whole-product journeys against that same serial server?

`--runs` / `--concurrency` overlap **entire journeys**. Do not parallelize
turns, sessions, or supervisor passes inside one journey.

`run_overlap_factor` in `suite.json` is the sum of parent-observed child
subprocess walls divided by suite wall. It measures outstanding
simulation-process overlap, **not** MTPLX inference parallelism.

Configured replica/session/turn counts are identical across C1/C2/C4. That is
**fixed configured workload**, not bit-identical computational work: the
synthetic patient and therapist are stochastic, so intake length, response
lengths, token counts, and correction attempts can vary. Repeated Stage 2
observations mitigate that.

## Frozen fixture

Phase 8C uses the current MTPLX backend with **one intentional inference
change** from the reusable 8B launch: Qwen 3.8 reasoning effort is `low` at
both the MTPLX launch flag and the request extra body. Do **not** compare
absolute 8C walls to original Phase 8B timings. Backend version and reasoning
effort both differ. All 8C concurrency rows use this same fixture.

```text
Original Phase 8B measurements: MTPLX 2.7.1, effective Qwen3.8
reasoning effort medium via the then-default behavior.
The reusable 8B common.sh pins that effective behavior explicitly as medium.

Phase 8C: MTPLX 2.8.1, reasoning_effort=low at both server and request.
```

- Qwen3.8-27B: `Youssofal/Qwen3.8-27B-MTPLX-Optimized-Speed`
- MTPLX 2.8.1, serial scheduler, `--ssd-session-cache off`,
  `--reasoning-effort low`
- thinking enabled; request `reasoning_effort=low`; `top_p=0.95`; `top_k=20`
- default Jung task policies (`json_schema` for structured supervisor/state
  calls)
- `JUNG_LLM_TASK_CONFIG_JSON` absent/empty unless recorded as part of this
  fixture
- `JUNG_SIM_PATIENT_THINKING_PREFILL` absent/false
- omit `--patient-model` and `--patient-base-url` (patient uses the session
  endpoint/model and inherits session extra body)
- explicit frozen `--style` (assessment still runs)

Before the first timed 8C row, the freeze may move to a newer validated
stable MTPLX. After the first timed row, the selected `MTPLX_VERSION` is
immutable until C1/C2/C4 closes. If PyPI publishes a newer stable before the
remaining rows complete, keep the frozen version and set
`PHASE8B_ALLOW_OLD_MTPLX=1`. That bypasses **only** freshness; metadata
equality and CLI-banner containment must still validate the frozen version.
Record the override in the worksheet / eventual `OUTCOME.md`.

```bash
export JUNG_LLM_EXTRA_BODY_JSON='{"chat_template_kwargs":{"enable_thinking":true},"reasoning_effort":"low","top_p":0.95,"top_k":20}'
```

If supervisor extras are set explicitly, they **replace** session extras —
repeat the complete object:

```bash
export JUNG_SUPERVISOR_LLM_EXTRA_BODY_JSON='{"chat_template_kwargs":{"enable_thinking":true},"reasoning_effort":"low","top_p":0.95,"top_k":20}'
```

Simulation uses production Jung env (`LLM_BASE_URL`, `MODEL_NAME`, supervisor
settings). Smoke uses `LOCAL_LLM_SMOKE_*`. Freeze **both** resolved
configurations, including values that arrive via `.env`. Session and
supervisor must resolve to the same intended MTPLX/Qwen3.8 fixture.

```bash
export LOCAL_LLM_SMOKE_EXTRA_BODY='{"chat_template_kwargs":{"enable_thinking":true},"reasoning_effort":"low","top_p":0.95,"top_k":20}'
```

Timed rows require a **clean Git worktree**.

## CLI

Default remains `--runs 1 --concurrency 1` (legacy in-process journey). Pass
flags through `SIM_ARGS` — extra tokens after `make` are Make options:

```bash
make simulate-local-llm \
  SIM_ARGS="--scenario social_anxiety --sessions 2 --turns-per-session 4 \
  --style <frozen-style> --runs 4 --concurrency 4"
```

`--output-dir` is the journey directory when `--runs 1` and the suite
directory when `--runs > 1`. `--concurrency` must be `<= --runs`.

## Preflight (required before timed rows)

1. `make check` for the implementation (already required to land the
   scheduler). Do not rerun `make evals` / `make eval-report` merely because
   the parent scheduler changed.
2. Confirm resolved Jung and smoke settings (including `.env`) match the
   fixture.
3. `make smoke-local-llm` with the extras above.
4. One very short concurrent suite as operational proof. Abort timed
   measurements unless a child `run.json` shows the expected session,
   supervisor, and patient endpoints/models and default structured modes.

If a real-model surface cannot run, record **not run**. Never infer success
from deterministic tests.

## Every timed observation

Server startup and warm-up stay **outside** `suite_wall_seconds`.

```text
stop MTPLX
    ↓
start frozen serial MTPLX
  (--ssd-session-cache off, --reasoning-effort low, 8C sampling/thinking)
    ↓
readiness/provenance check
    ↓
fixed dummy warm
    ↓
timed simulation suite
    ↓
stop MTPLX
```

## Stages

Short workload example: `social_anxiety`, explicit frozen style, 2 sessions ×
4 turns, 4 replicas. Long workload example: 4 runs × 4 sessions × 8 turns.

```text
C1: --runs 4 --concurrency 1
C2: --runs 4 --concurrency 2
C4: --runs 4 --concurrency 4
```

**Stage 1.** Run C1, C2, C4 once on the short workload. C1 must succeed. At
least one of C2/C4 must succeed. Failed rows do not advance. Among successful
rows, the two lowest suite-wall times advance to Stage 2. Do not pool Stage 1
timings into Stage 2. Without a viable serial control, the benchmark cannot
close as a speedup comparison.

**Stage 2.** Three **counterbalanced** short observations per finalist
(`A→B`, `B→A`, `A→B`). Rank by median suite wall.

Define `selected_concurrent_candidate`:

- finalists C2+C4 → their median winner
- finalists C1+Cx → Cx (the concurrent row, even if C1 beat it)

**Stage 3.** Always `selected_concurrent_candidate vs C1`, one long
observation each, opposite/counterbalanced order.

**Stage 4.** One further long observation each, reversing Stage 3 execution
order, if:

- absolute Stage 3 gap `< 10%`, or
- the long result contradicts the relevant screen conclusion, or
- C1 was absent from Stage 2 and Stage 3 is a C1 win

Final ranking = mean(Stage 3, Stage 4).

No required speedup threshold. A measured ceiling (including C1 ≈ C4) is a
valid result. Document the measured recommendation in `OUTCOME.md`; do not
change the CLI default (`--concurrency 1`).

## Provenance freeze (every timed row)

```text
source revision / clean worktree
resolved LLM_BASE_URL / MODEL_NAME (and supervisor if set) = same MTPLX/Qwen3.8
resolved LOCAL_LLM_SMOKE_* = same fixture
preflight short-suite run.json matches expected endpoints/models/structured modes
MTPLX 2.8.1, serial, SSD session cache off, --reasoning-effort low
enable_thinking true, request reasoning_effort low, top_p .95, top_k 20
default Jung task policies; JUNG_LLM_TASK_CONFIG_JSON empty
JUNG_SIM_PATIENT_THINKING_PREFILL absent/false
same patient endpoint/model (no --patient-model / --patient-base-url)
scenario / requested_style / sessions / turns
```
