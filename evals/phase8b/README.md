# Phase 8B operator scripts

Reproducible benchmark funnel for local server scheduling (see
[`evals/README.md`](../README.md) Phase 8B). **Closed results:**
[`OUTCOME.md`](OUTCOME.md).

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

Runtime output (metrics, logs, local worksheet) goes to **gitignored**
`logs/evals/phase8b/` — never under tracked `evals/phase8b/`.

## Prerequisites

- Jung dev env (`uv sync`, `make check` baseline)
- **Clean Git working tree** — scripts refuse to run with uncommitted changes so
  `fixture-manifest.json` `source_revision` identifies executed code
- Qwen3.8-27B llama.cpp GGUF and MTPLX Optimized Speed artifact (see OUTCOME)
- MTPLX **2.7.1** venv with `llguidance` for `json_schema`:

```bash
/opt/homebrew/var/mtplx/venv-2.7.1/bin/python -m pip install 'llguidance>=1.7'
```

All MTPLX commands use `$MTPLX_BREW_VENV/bin/mtplx` (see `MTPLX_BIN` below).

## Environment overrides

| Variable | Default |
|---|---|
| `PHASE8B_LOGDIR` | `logs/evals/phase8b` under repo root |
| `LLAMA_SERVER` | `$HOME/experiments/llama.cpp/build/bin/llama-server` |
| `GGUF_PATH` | `$HOME/data/models/llm/gguf/.../Qwen3.8-27B-Q4_K_M.gguf` |
| `MTPLX_BREW_VENV` | `/opt/homebrew/var/mtplx/venv-2.7.1` |
| `MTPLX_BIN` | `$MTPLX_BREW_VENV/bin/mtplx` |
| `MTPLX_MODEL` | `Youssofal/Qwen3.8-27B-MTPLX-Optimized-Speed` |
| `PHASE8B_RESUME` | Stage 1 anchor: `M1`, `M4`, `A2`, `A4`, `T4`, `L1` |
| `PHASE8B_STAGE3_RESUME` | `L1`, `M4`, `M1`, or `STAGE4` |
| `PHASE8B_L1_RETRY_1800` | `0` — set to `1` for diagnostic `L1-full-retry-1800` only |

Resume refuses to continue when `fixture-manifest.json` or an existing row
`*.metrics.json` implies a different fixture/workload/`report_jobs` count.

Invalid resume values fail immediately.

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
warm → timed row. MTPLX timed launches use `--ssd-session-cache off`.

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

**M4** — MTPLX serial scheduler, client concurrency 4. See OUTCOME.md for
margins and limitations. Concurrent eval-report default: **M4**. Interactive
serial reference: **M1**.
