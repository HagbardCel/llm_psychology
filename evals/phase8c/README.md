# Phase 8C — parallel independent longitudinal simulations

Experiment contract for overlapping complete `simulate-local-llm` journeys.
`OUTCOME.md` records the live benchmark outcome and the protocol-amendment
history.

**Protocol amended: 2026-08-19.** The original Stage 1-4 escalation was
replaced with a cost-bounded two-stage decision contract: Stage 1 C1/C2/C4
screen, then a conditional single Stage 2 confirmation pair. Long-workload
Stage 3/4 benchmarks are removed. Reason: the original escalation imposed
disproportionate real-model runtime relative to the engineering decision
Phase 8C actually needs to make.

This protocol amendment was made in-flight to cap experiment cost/runtime;
it should not be interpreted as a preregistered statistical protocol.

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
lengths, token counts, and correction attempts can vary. Phase 8C uses a
decision-oriented confirmation boundary rather than repeated median
estimation.

## Frozen fixture

Phase 8C uses the current MTPLX backend with **one intentional inference
change** from the reusable 8B launch: Qwen 3.8 reasoning effort is `low` at
both the MTPLX launch flag and the request extra body. Do **not** compare
absolute 8C walls to original Phase 8B timings. Backend version and reasoning
effort both differ. All 8C concurrency rows use this same fixture.

```text
Original Phase 8B measurements: MTPLX 2.7.1, with server
`--reasoning-effort medium`. Requests did not specify request-level
`reasoning_effort`, so they did not override the server-level medium setting.

Phase 8C: MTPLX 2.8.1, with `reasoning_effort=low` explicitly at both
server and request.
```

- Qwen3.8-27B: `Youssofal/Qwen3.8-27B-MTPLX-Optimized-Speed`
- MTPLX 2.8.1, serial scheduler, `--ssd-session-cache off`,
  `--reasoning-effort low`
- thinking enabled; request `reasoning_effort=low`; `top_p=0.95`; `top_k=20`
- default Jung task policies (`json_schema` for structured supervisor/state
  calls)
- frozen `JUNG_LLM_TASK_CONFIG_JSON` timeout override (timeout_seconds=600
  on all six tasks):
  `{"intake_patch":{"timeout_seconds":600},"intake_response":{"timeout_seconds":600},"therapy_response":{"timeout_seconds":600},"assessment":{"timeout_seconds":600},"post_session_analysis":{"timeout_seconds":600},"post_session_update":{"timeout_seconds":600}}`
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

## Stages (cost-bounded decision: short Stage 1 -> conditional Stage 2 -> stop)

Short workload example: `social_anxiety`, explicit frozen style, 2 sessions ×
4 turns, 4 replicas.

```text
C1: --runs 4 --concurrency 1
C2: --runs 4 --concurrency 2
C4: --runs 4 --concurrency 4
```

### Mechanically valid timed row (minimum)

For a timed row to count toward speedup decisions, it must be mechanically valid:

`suite.json` exists and parses,
`suite.status == complete`,
all 4 child runs are complete,
`suite_wall_seconds > 0`,
`git_worktree_dirty == false`,
fixture identity fields match (scenario/style/sessions/turns/runs and the frozen
short-workload config),
clean accepted provenance/protocol-freeze match,
and for C2/C4: `max_observed_concurrency == requested_concurrency`.

`run_overlap_factor` is diagnostic/explanatory only (not a pass/fail gate).

### External invalidation vs valid observed failure (replacement-cap contract)

Use a strict two-category interpretation. This is how we avoid an accidental
infinite rerun loop.

Observation invalid (external invalidation) - may be replaced:

- wrong MTPLX version/model/config
- wrong reasoning/sampling/configuration
- wrong scenario/style/session/turn/replica/concurrency fixture
- accidental wrong endpoint/model
- dirty/unapproved source state
- wrong server lifecycle/configuration
- provenance/config provenance mismatch discovered before interpretation
- operator interruption
- machine sleep/reboot or unrelated process termination
- missing/corrupt timing evidence caused by measurement infrastructure defect

Observation valid but unsuccessful - counts against that row and is not retried:

- patient generation failure
- structured-output/correction failure
- application failure
- request/workflow timeout under the frozen fixture
- child process failure / non-zero exit
- MTPLX crash/OOM/instability while executing the correctly configured frozen workload
  (counts as evidence against that row)
- correction attempts
- unusually long generated responses
- poor timing
- near tie / ranking reversal

Retry policy:

- no automatic retries
- at most one documented replacement attempt per externally invalidated observation
- if the replacement is also externally invalidated, close Phase 8C as inconclusive
  and retain the default `--concurrency 1`

### Stage 1: existing C1/C2/C4 short fixture (one observation each)

Run C1, C2, C4 once on the short workload (the runs you are already doing).

Preconditions:

- C1 must be mechanically valid and successful
- at least one of C2/C4 must be mechanically valid and successful

If Stage 1 preconditions fail:

- Valid C1 + no successful valid C2/C4 -> close Phase 8C, retain C1, stop reason:
  no viable concurrent candidate
- No valid C1 after the permitted external-invalid replacement -> close Phase 8C
  as inconclusive; keep CLI default `--concurrency 1`; no concurrency recommendation
- C1 has a genuine (counted) workload failure -> close Phase 8C as inconclusive; retain C1

Candidate selection (no top-two finalist pooling):

- `candidate = fastest mechanically-valid successful row among {C2, C4}`
- `control = C1`

Decision function (closed boundary, exact +10% does not advance):

`stage1_speedup = (stage1_C1_wall - stage1_candidate_wall) / stage1_C1_wall`

| Condition | Result |
|---|---|
| `stage1_speedup <= 0.10` | stop; retain `C1` |
| `stage1_speedup > 0.10` | run Stage 2 |

### Stage 2: conditional single confirmation pair only

Stage 2 runs only when Stage 1 produces `stage1_speedup > 0.10`.

Execution order (deterministic counterbalancing):

- If Stage 1 ran `C1` before the selected `candidate`, run `candidate -> C1` in Stage 2.
- If the selected `candidate` occurred before `C1` in Stage 1, run `C1 -> candidate` in Stage 2.

Stage 2 workload:

- `C1` and `candidate` each run once on the same short fixture:
  `--runs 4 --concurrency 1` vs `--runs 4 --concurrency {2|4}`

Stage 2 statistics framing:

- one suite observation per arm (`n=1` suites)
- each suite contains four independent journey replicas (`4` child runs)

Stage 2 compares its own paired observations only:

`stage2_speedup = (stage2_C1_wall - stage2_candidate_wall) / stage2_C1_wall`

Stage 2 decision (closed boundary, exact +10% does not advance):

- if Stage 2 cannot produce a valid comparison -> stop; retain C1; do not recommend candidate
- if `stage2_speedup <= 0.10` -> stop; retain C1
- if `stage2_speedup > 0.10` -> recommend candidate

Stage 2 failure outcomes:

- Stage 2 candidate has a genuine workload failure -> retain C1
- Stage 2 `C1` has a genuine workload failure -> confirmation is inconclusive; retain C1
  and do not promote candidate from timing evidence alone

### Stage 3 and Stage 4

Deleted from Phase 8C. No long-workload benchmark work is part of this decision contract.

### In-flight protocol amendment: source revision grandfathering

`OUTCOME.md` and the amended contract must treat source revision carefully because Stage 1 was
already started before this documentation-only amendment.

- `stage1 benchmark source revision` (the commit recorded for the Stage 1 timed rows)
- `stage2 benchmark source revision` (may differ if only Markdown/docs changed after Stage 1 started)
- `protocol revision/date` (this amendment: 2026-08-19)

Freeze rule:

The 2026-08-19 protocol-only documentation amendment does not invalidate already-running Stage 1
observations as long as the diff since the Stage 1 benchmark revision contains no changes to:
Jung runtime code, `evals/simulation/**`, dependency resolution, or the frozen short benchmark fixture.

### Recommendation impact (what “recommend candidate” changes)

Phase 8C recommendation selects the preferred operator concurrency for the frozen local simulation
fixture. It does not change the CLI default, production behavior, or simulation scheduler code.
“Retain C1” means the operator default remains `--concurrency 1`.

### Evidence invalidation policy for Phase 8C

Phase 8C evidence is invalidated by changes to:

- whole-journey concurrency scheduling semantics
- subprocess orchestration
- concurrency limit semantics
- MTPLX scheduler configuration or MTPLX version where performance characteristics may differ
- model or quant
- reasoning mode/effort
- sampling configuration with material generation-cost implications
- simulation request topology
- number/type of product LLM calls
- patient simulator behavior that materially changes workload
- the frozen benchmark fixture

Phase 8C evidence is not invalidated by:

- report formatting, Markdown changes, or JSON rendering changes
- documentation updates
- artifact naming, logs rendering, or parsing/reporting of already-captured data
- unrelated production changes that do not alter the LLM call path

### Validation hierarchy (Tier A–D) for Phase 8-style work

Tier selection is change-sensitive, but it does not waive experiment-contract preconditions.

- Tier A (deterministic software correctness): `make check` + focused deterministic tests
  required when executable/product code can be affected
- Tier B (live provider/model compatibility): `make smoke-local-llm` + targeted hard real-model checks
  required when provider/config/structured-output compatibility can be affected
- Tier C (targeted empirical performance/concurrency property): frozen short benchmark evidence
  required when the change/decision concerns performance/concurrency
- Tier D (broad longitudinal whole-product behavior): meaningful multi-session `simulate-local-llm` evidence
  required when longitudinal behavior/memory/supervision can plausibly change

Governing rule:

Tiers are not cumulative maturity levels. Use the lowest-cost tier(s) that measure the properties the
change can plausibly invalidate; existing higher-tier frozen evidence remains valid when the change
cannot affect the property it measured.

## Provenance freeze (every timed row)

```text
source revision / clean worktree
resolved LLM_BASE_URL / MODEL_NAME (and supervisor if set) = same MTPLX/Qwen3.8
resolved LOCAL_LLM_SMOKE_* = same fixture
preflight short-suite run.json matches expected endpoints/models/structured modes
MTPLX 2.8.1, serial, SSD session cache off, --reasoning-effort low
enable_thinking true, request reasoning_effort low, top_p .95, top_k 20
default Jung task policies except frozen timeout override via
JUNG_LLM_TASK_CONFIG_JSON={"intake_patch":{"timeout_seconds":600},"intake_response":{"timeout_seconds":600},"therapy_response":{"timeout_seconds":600},"assessment":{"timeout_seconds":600},"post_session_analysis":{"timeout_seconds":600},"post_session_update":{"timeout_seconds":600}}
JUNG_SIM_PATIENT_THINKING_PREFILL absent/false
same patient endpoint/model (no --patient-model / --patient-base-url)
scenario / requested_style / sessions / turns
```
