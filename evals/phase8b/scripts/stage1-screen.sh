#!/bin/bash
# Phase 8B Stage 1 — screen matrix. Run from repo root in Terminal.app (Metal/GPU).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"
phase8b_common_init
phase8b_bootstrap

export LOCAL_LLM_SMOKE_REQUEST_TIMEOUT=600
export_mtplx_smoke_env

RESUME="${PHASE8B_RESUME:-}"
validate_stage1_resume "$RESUME"

echo "=== Phase 8B Stage 1 screening ==="
echo "Worksheet: $WORKSHEET"
echo "Logdir: $LOGDIR"

ensure_llguidance
assert_mtplx_freeze

MTPLX_SMOKE_OK=0
LLAMA_SMOKE_OK=0

if [[ -z "$RESUME" || "$RESUME" == "M1" || "$RESUME" == "M4" || "$RESUME" == "A2" || "$RESUME" == "A4" || "$RESUME" == "T4" ]]; then
  start_mtplx serial "$LOGDIR/mtplx-serial-smoke.log"
  preflight_json_schema "http://127.0.0.1:$MTPLX_PORT/v1"
  dummy_warm "http://127.0.0.1:$MTPLX_PORT/v1"
  if run_smoke_gate "$LOGDIR/smoke-mtplx.log"; then
    MTPLX_SMOKE_OK=1
  else
    record_compatibility_failure mtplx-screen mtplx "$LOGDIR/smoke-mtplx.log"
    echo "MTPLX screen: compatibility failure — skipping all MTPLX timed rows"
  fi
  stop_mtplx
fi

if [[ "$MTPLX_SMOKE_OK" == 1 && ( -z "$RESUME" || "$RESUME" == "M1" ) ]]; then
  assert_metrics_resume_ok M1 screen 8
  start_mtplx serial "$LOGDIR/mtplx-M1.log"
  preflight_json_schema "http://127.0.0.1:$MTPLX_PORT/v1"
  dummy_warm "http://127.0.0.1:$MTPLX_PORT/v1"
  run_eval_screen 1
  record_metrics M1
  cp "$ROOT/logs/evals/latest.md" "$LOGDIR/M1.md" 2>/dev/null || true
  RESUME=""
fi

if [[ "$MTPLX_SMOKE_OK" == 1 && ( -z "$RESUME" || "$RESUME" == "M4" ) ]]; then
  assert_metrics_resume_ok M4 screen 8
  start_mtplx serial "$LOGDIR/mtplx-M4.log"
  preflight_json_schema "http://127.0.0.1:$MTPLX_PORT/v1"
  dummy_warm "http://127.0.0.1:$MTPLX_PORT/v1"
  run_eval_screen 4
  record_metrics M4
  cp "$ROOT/logs/evals/latest.md" "$LOGDIR/M4.md" 2>/dev/null || true
  RESUME=""
fi

if [[ "$MTPLX_SMOKE_OK" == 1 && ( -z "$RESUME" || "$RESUME" == "A2" || "$RESUME" == "A4" ) ]]; then
  if [[ "$RESUME" == "A4" ]]; then
    if start_mtplx ar_batch "$LOGDIR/mtplx-A4.log"; then
      preflight_json_schema "http://127.0.0.1:$MTPLX_PORT/v1"
      dummy_warm "http://127.0.0.1:$MTPLX_PORT/v1"
      run_eval_screen 4
      record_metrics A4
    else
      echo "A4: unsupported or failed construction"
    fi
  elif start_mtplx ar_batch "$LOGDIR/mtplx-A2.log"; then
    preflight_json_schema "http://127.0.0.1:$MTPLX_PORT/v1"
    dummy_warm "http://127.0.0.1:$MTPLX_PORT/v1"
    run_eval_screen 2
    record_metrics A2
    start_mtplx ar_batch "$LOGDIR/mtplx-A4.log"
    preflight_json_schema "http://127.0.0.1:$MTPLX_PORT/v1"
    dummy_warm "http://127.0.0.1:$MTPLX_PORT/v1"
    run_eval_screen 4
    record_metrics A4
  else
    echo "A2/A4: unsupported or failed construction"
  fi
  RESUME=""
fi

if [[ "$MTPLX_SMOKE_OK" == 1 && ( -z "$RESUME" || "$RESUME" == "T4" ) ]]; then
  if start_mtplx mtp_batch "$LOGDIR/mtplx-T4.log"; then
    preflight_json_schema "http://127.0.0.1:$MTPLX_PORT/v1"
    dummy_warm "http://127.0.0.1:$MTPLX_PORT/v1"
    run_eval_screen 4
    record_metrics T4
  else
    echo "T4: not supported by tested MTPLX build / Qwen3.8 lane"
  fi
  RESUME=""
fi

stop_mtplx
sleep 1

if [[ -z "$RESUME" || "$RESUME" == "L1" ]]; then
  export_llama_smoke_env
  start_llama 1 "$LOGDIR/llama-L1-smoke.log"
  dummy_warm "http://127.0.0.1:$LLAMA_PORT/v1"
  if run_smoke_gate "$LOGDIR/smoke-llama.log"; then
    LLAMA_SMOKE_OK=1
  else
    record_compatibility_failure llama-screen llama.cpp "$LOGDIR/smoke-llama.log"
    echo "llama screen: compatibility failure — skipping all llama timed rows"
  fi
  stop_llama
fi

if [[ "$LLAMA_SMOKE_OK" == 1 && ( -z "$RESUME" || "$RESUME" == "L1" ) ]]; then
  start_llama 1 "$LOGDIR/llama-L1.log"
  dummy_warm "http://127.0.0.1:$LLAMA_PORT/v1"
  run_eval_screen 1
  record_metrics L1
  cp "$ROOT/logs/evals/latest.md" "$LOGDIR/L1.md" 2>/dev/null || true

  start_llama 2 "$LOGDIR/llama-L2.log"
  dummy_warm "http://127.0.0.1:$LLAMA_PORT/v1"
  run_eval_screen 2
  record_metrics L2

  if start_llama 4 "$LOGDIR/llama-L4.log"; then
    dummy_warm "http://127.0.0.1:$LLAMA_PORT/v1"
    run_eval_screen 4
    record_metrics L4
  else
    echo "L4: infeasible (context/memory)"
  fi
  stop_llama
fi

echo "=== Stage 1 complete. Metrics under $LOGDIR ==="
echo "Next: stage2-confirm.sh for top-two confirmation."
