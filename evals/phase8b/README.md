# Phase 8B operator scripts

Reproducible benchmark funnel for local server scheduling (see
[`evals/README.md`](../README.md) Phase 8B). **Closed results:**
[`OUTCOME.md`](OUTCOME.md) records the original matrix on MTPLX **2.7.1**.

`common.sh` and the operator infrastructure are maintained for the **current**
MTPLX backend. The stage scripts retain the original Phase 8B experiment
topology; Stage 2/3 keep the historical M1/M4 finalist structure and are not a
generic backend re-selection framework. Each execution records its exact
fixture and runtime in `fixture-manifest.json`. Later runs are separate
revalidations, not continuations of the closed 2.7.1 comparison.

Run from the **repository root** in **Terminal.app** on a Mac with Metal/GPU.
Cursor agent shells cannot access GPU; do not run these scripts from the agent.

## Layout

```text
evals/phase8b/scripts/
  common.sh          shared helpers (paths, MTPLX/llama launch, metrics)
  stage1-screen.sh   Stage 1 screen matrix
  stage2-confirm.sh  Stage 2 M1/M4 confirmation (3 alternating runs each)
  stage3-full.sh     Stage 3 full L1 + M4 + M1; auto Stage 4 tie-break
```

Default runtime output is gitignored
`logs/evals/phase8b/mtplx-${MTPLX_VERSION}/`. Historical unversioned
`logs/evals/phase8b/` is 2.7.1 / v1 evidence — do not migrate it, and do not
resume a new run over it. Never write under tracked `evals/phase8b/`.

## Prerequisites

- Jung dev env (`uv sync`, `make check` baseline)
- **Clean Git working tree** — scripts refuse to run with uncommitted or
  untracked changes so `fixture-manifest.json` `source_revision` identifies
  executed code
- When using the scripts after the original Phase 8B run, use a fresh
  `PHASE8B_LOGDIR` (or accept the versioned default); pre-manifest historical
  artifacts are evidence, not resumable script state
- Qwen3.8-27B llama.cpp GGUF and MTPLX Optimized Speed artifact (see OUTCOME)
- Current MTPLX venv (`MTPLX_VERSION`, default **2.8.1**) with `llguidance`
  for `json_schema`:

```bash
/opt/homebrew/var/mtplx/venv-2.8.1/bin/python -m pip install 'llguidance>=1.7'
```

All MTPLX commands use `$MTPLX_BIN`. `MTPLX_PY` defaults to the `python` next
to that binary so metadata and `llguidance` checks describe the environment
that launches the server.

Identity: package metadata must equal `MTPLX_VERSION`; the full `mtplx
--version` banner must **contain** that version (the 2.8.1 wheel reports
`mtplx 2.8.0 (2.8.1)`). Timed MTPLX starts also require PyPI’s current stable
`mtplx` to equal `MTPLX_VERSION` (5s timeout; network failure refuses). Set
`PHASE8B_ALLOW_OLD_MTPLX=1` to skip **only** that freshness check — for
example after the first timed Phase 8C row, if upstream publishes a newer
stable before the remaining C rows finish. Metadata and CLI-banner checks
still apply. The scripts never upgrade packages.

`llguidance_version` is written as `null` at bootstrap (llama.cpp-only L1
resume must not query the MTPLX venv) and sealed from `importlib.metadata` on
the first MTPLX start.

## Environment overrides

| Variable | Default |
|---|---|
| `MTPLX_VERSION` | `2.8.1` |
| `PHASE8B_LOGDIR` | `logs/evals/phase8b/mtplx-${MTPLX_VERSION}` under repo root |
| `LLAMA_SERVER` | `$HOME/experiments/llama.cpp/build/bin/llama-server` |
| `GGUF_PATH` | `$HOME/data/models/llm/gguf/.../Qwen3.8-27B-Q4_K_M.gguf` |
| `MTPLX_BREW_VENV` | `/opt/homebrew/var/mtplx/venv-${MTPLX_VERSION}` |
| `MTPLX_BIN` | `$MTPLX_BREW_VENV/bin/mtplx` |
| `MTPLX_PY` | `$(dirname "$MTPLX_BIN")/python` |
| `MTPLX_MODEL` | `Youssofal/Qwen3.8-27B-MTPLX-Optimized-Speed` |
| `PHASE8B_ALLOW_OLD_MTPLX` | unset — set to `1` to skip the PyPI freshness check |
| `PHASE8B_RESUME` | Stage 1 anchor: `M1`, `M4`, `A2`, `A4`, `T4`, `L1` |
| `PHASE8B_STAGE3_RESUME` | `L1`, `M4`, `M1`, or `STAGE4` |
| `PHASE8B_L1_RETRY_1800` | `0` — set to `1` for diagnostic `L1-full-retry-1800` only |

Resume refuses to continue when `fixture-manifest.json` or an existing row
`*.metrics.json` implies a different fixture/workload/`report_jobs` count.

Invalid resume values fail immediately.

The 8B inference fixture is unchanged: request extras stay
`enable_thinking=true`, `top_p=0.95`, `top_k=20` with no request-level
`reasoning_effort`. Timed MTPLX launches pin `--reasoning-effort medium` and
`--ssd-session-cache off`.

## Run order

```bash
bash evals/phase8b/scripts/stage1-screen.sh
bash evals/phase8b/scripts/stage2-confirm.sh
bash evals/phase8b/scripts/stage3-full.sh
```

Each stage: stop → configure server → readiness/provenance → dummy warm →
timed `make eval-report` → record metrics → stop. Use `--workload screen` in
stages 1–2 and `--workload full` in stage 3 (handled by the scripts).

`make smoke-local-llm` is the **json_schema compatibility gate** — a failed
smoke never produces a timed row. After a passing smoke: restart server → dummy
warm → timed row.

Only one Phase 8B script may run at a time (lock directory `$LOGDIR/.lock`).
Fixed ports 8000 (MTPLX) and 8080 (llama.cpp) and shared
`logs/evals/latest.metrics.json` make concurrent runs unsafe. If a script was
killed abruptly, remove `.lock` manually after verifying no Phase 8B script is
running.

## Stage 4 ranking

When Stage 4 runs, rank finalists by the **arithmetic mean** of their Stage 3
and Stage 4 full-workload walls (two observations per finalist).

## L1-full timeout

Canonical `L1-full` uses `LOCAL_LLM_SMOKE_REQUEST_TIMEOUT=600`. Optional
`L1-full-retry-1800` (requires `PHASE8B_L1_RETRY_1800=1` after a canonical
failure in the same run) is diagnostic only and excluded from ranking.

## Winner (closed matrix)

**M4** — MTPLX serial scheduler, client concurrency 4, measured on MTPLX
2.7.1. See OUTCOME.md for margins and limitations. Concurrent eval-report
default: **M4**. Interactive serial reference: **M1**.
