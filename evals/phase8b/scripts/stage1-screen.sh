#!/bin/bash
# Phase 8B Stage 1 — screen matrix. Run from repo root in Terminal.app (Metal/GPU).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"
phase8b_common_init

export LOCAL_LLM_SMOKE_REQUEST_TIMEOUT=600
export_mtplx_smoke_env

echo "=== Phase 8B Stage 1 screening ==="
echo "Worksheet: $WORKSHEET"
echo "Logdir: $LOGDIR"

ensure_llguidance
assert_mtplx_freeze

RESUME="${PHASE8B_RESUME:-}"

if [[ -z "$RESUME" || "$RESUME" == "M1" ]]; then
  assert_metrics_resume_ok M1 screen 8
  start_mtplx serial "$LOGDIR/mtplx-serial.log"
  preflight_json_schema http://127.0.0.1:8000/v1
  dummy_warm http://127.0.0.1:8000/v1
  make smoke-local-llm | tee "$LOGDIR/smoke-mtplx.log" || {
    echo "WARNING: mtplx smoke failed; continuing to timed screen rows"
  }
  start_mtplx serial "$LOGDIR/mtplx-M1.log"
  preflight_json_schema http://127.0.0.1:8000/v1
  dummy_warm http://127.0.0.1:8000/v1
  run_eval_screen 1
  record_metrics M1
  cp "$ROOT/logs/evals/latest.md" "$LOGDIR/M1.md" 2>/dev/null || true

  assert_metrics_resume_ok M4 screen 8
  start_mtplx serial "$LOGDIR/mtplx-M4.log"
  preflight_json_schema http://127.0.0.1:8000/v1
  dummy_warm http://127.0.0.1:8000/v1
  run_eval_screen 4
  record_metrics M4
  cp "$ROOT/logs/evals/latest.md" "$LOGDIR/M4.md" 2>/dev/null || true
  RESUME=""
fi

if [[ -z "$RESUME" || "$RESUME" == "A2" || "$RESUME" == "A4" ]]; then
  if [[ "$RESUME" == "A4" ]]; then
    if start_mtplx ar_batch "$LOGDIR/mtplx-A4.log"; then
      preflight_json_schema http://127.0.0.1:8000/v1
      dummy_warm http://127.0.0.1:8000/v1
      run_eval_screen 4
      record_metrics A4
    else
      echo "A4: unsupported or failed construction"
    fi
  elif start_mtplx ar_batch "$LOGDIR/mtplx-A2.log"; then
    preflight_json_schema http://127.0.0.1:8000/v1
    dummy_warm http://127.0.0.1:8000/v1
    run_eval_screen 2
    record_metrics A2
    start_mtplx ar_batch "$LOGDIR/mtplx-A4.log"
    preflight_json_schema http://127.0.0.1:8000/v1
    dummy_warm http://127.0.0.1:8000/v1
    run_eval_screen 4
    record_metrics A4
  else
    echo "A2/A4: unsupported or failed construction"
  fi
  RESUME=""
fi

if [[ -z "$RESUME" || "$RESUME" == "T4" ]]; then
  if start_mtplx mtp_batch "$LOGDIR/mtplx-T4.log"; then
    preflight_json_schema http://127.0.0.1:8000/v1
    dummy_warm http://127.0.0.1:8000/v1
    run_eval_screen 4
    record_metrics T4
  else
    echo "T4: not supported by tested MTPLX build / Qwen3.8 lane"
  fi
  RESUME=""
fi

mtplx stop --port 8000 2>/dev/null || true
sleep 3

if [[ -z "$RESUME" || "$RESUME" == "L1" ]]; then
  export_llama_smoke_env
  start_llama 1 "$LOGDIR/llama-L1.log"
  dummy_warm http://127.0.0.1:8080/v1
  make smoke-local-llm | tee "$LOGDIR/smoke-llama.log" || true
  start_llama 1 "$LOGDIR/llama-L1.log"
  dummy_warm http://127.0.0.1:8080/v1
  run_eval_screen 1
  record_metrics L1
  cp "$ROOT/logs/evals/latest.md" "$LOGDIR/L1.md" 2>/dev/null || true

  start_llama 2 "$LOGDIR/llama-L2.log"
  dummy_warm http://127.0.0.1:8080/v1
  run_eval_screen 2
  record_metrics L2

  start_llama 4 "$LOGDIR/llama-L4.log" || {
    echo "L4: infeasible (context/memory)"
  }
  if [[ -f "$LOGDIR/llama.pid" ]] && kill -0 "$(cat "$LOGDIR/llama.pid")" 2>/dev/null; then
    slots=$(curl -s http://127.0.0.1:8080/props | python3 -c 'import sys,json;print(json.load(sys.stdin).get("total_slots"))')
    if [[ "$slots" == "4" ]]; then
      dummy_warm http://127.0.0.1:8080/v1
      run_eval_screen 4
      record_metrics L4
    else
      echo "L4 aborted: total_slots=$slots"
    fi
  fi
fi

echo "=== Stage 1 complete. Metrics under $LOGDIR ==="
echo "Next: stage2-confirm.sh for top-two confirmation."
