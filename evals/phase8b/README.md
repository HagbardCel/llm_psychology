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
- Qwen3.8-27B llama.cpp GGUF and MTPLX Optimized Speed artifact (see OUTCOME)
- MTPLX **2.7.1** venv with `llguidance` for `json_schema`:

```bash
/opt/homebrew/var/mtplx/venv-2.7.1/bin/python -m pip install 'llguidance>=1.7'
```

## Environment overrides

| Variable | Default |
|---|---|
| `PHASE8B_LOGDIR` | `logs/evals/phase8b` under repo root |
| `LLAMA_SERVER` | `$HOME/experiments/llama.cpp/build/bin/llama-server` |
| `GGUF_PATH` | `$HOME/data/models/llm/gguf/.../Qwen3.8-27B-Q4_K_M.gguf` |
| `MTPLX_BREW_VENV` | `/opt/homebrew/var/mtplx/venv-2.7.1` |
| `MTPLX_MODEL` | `Youssofal/Qwen3.8-27B-MTPLX-Optimized-Speed` |
| `PHASE8B_RESUME` | Stage 1 row id to resume from (`M1`, `L1`, …) |
| `PHASE8B_STAGE3_RESUME` | `L1`, `M4`, `M1`, or `STAGE4` |

Resume refuses to continue when existing `*.metrics.json` for a row has the
wrong `workload` or `report_jobs` count.

## Run order

```bash
bash evals/phase8b/scripts/stage1-screen.sh
bash evals/phase8b/scripts/stage2-confirm.sh
bash evals/phase8b/scripts/stage3-full.sh
```

Each stage: stop → configure server → readiness → dummy warm → timed
`make eval-report` → record metrics → stop. Use `--workload screen` in stages
1–2 and `--workload full` in stage 3 (handled by the scripts).

MTPLX timed launches use `--ssd-session-cache off`. Restart the server between
rows; `make smoke-local-llm` is a compatibility gate, not the timed warm-up.

## Winner (closed matrix)

**M4** — MTPLX serial scheduler, client concurrency 4. See OUTCOME.md for
margins and limitations. Concurrent eval-report default: **M4**. Interactive
serial reference: **M1**.
