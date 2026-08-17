#!/bin/bash
# Phase 8B Stage 2 — M1 vs M4 confirmation (3 alternating screen runs each).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"
phase8b_common_init

export LOCAL_LLM_SMOKE_REQUEST_TIMEOUT=600
export_mtplx_smoke_env

summarize_confirmation() {
  python3 - <<PY
import json, pathlib, statistics
logdir = pathlib.Path("$LOGDIR")
for cand in ("M1", "M4"):
    walls = []
    for i in range(1, 4):
        p = logdir / f"{cand}-c{i}.metrics.json"
        if not p.exists():
            print(f"missing {p.name}")
            continue
        m = json.loads(p.read_text())
        w = m.get("evaluation_wall_seconds")
        walls.append(w)
        print(f"{cand}-c{i} wall={w:.1f} workload={m.get('workload')} jobs={m.get('report_jobs')}")
    if len(walls) == 3:
        med = statistics.median(walls)
        print(f"{cand} median={med:.1f} walls={walls}")
print("--- Stage 2 rank by median screen wall ---")
rows = []
for cand in ("M1", "M4"):
    walls = []
    for i in range(1, 4):
        p = logdir / f"{cand}-c{i}.metrics.json"
        if p.exists():
            walls.append(float(json.loads(p.read_text())["evaluation_wall_seconds"]))
    if len(walls) == 3:
        rows.append((statistics.median(walls), cand, walls))
for med, cand, walls in sorted(rows):
    print(f"{cand}: median={med:.1f}  runs={[round(w,1) for w in walls]}")
PY
}

echo "=== Phase 8B Stage 2 confirmation (M1 ↔ M4) ==="
echo "Worksheet: $WORKSHEET"

ensure_llguidance
assert_mtplx_freeze

start_mtplx serial "$LOGDIR/mtplx-confirm-smoke.log"
preflight_json_schema http://127.0.0.1:8000/v1
dummy_warm http://127.0.0.1:8000/v1
make smoke-local-llm | tee "$LOGDIR/smoke-confirm-mtplx.log" || {
  echo "WARNING: mtplx smoke failed; continuing to confirmation rows"
}

for round in 1 2 3; do
  echo "=== confirm round ${round} / 3: M1 ==="
  assert_metrics_resume_ok "M1-c${round}" screen 8
  start_mtplx serial "$LOGDIR/mtplx-M1-c${round}.log"
  preflight_json_schema http://127.0.0.1:8000/v1
  dummy_warm http://127.0.0.1:8000/v1
  run_eval_screen 1
  record_metrics "M1-c${round}"
  cp "$ROOT/logs/evals/latest.md" "$LOGDIR/M1-c${round}.md" 2>/dev/null || true

  echo "=== confirm round ${round} / 3: M4 ==="
  assert_metrics_resume_ok "M4-c${round}" screen 8
  start_mtplx serial "$LOGDIR/mtplx-M4-c${round}.log"
  preflight_json_schema http://127.0.0.1:8000/v1
  dummy_warm http://127.0.0.1:8000/v1
  run_eval_screen 4
  record_metrics "M4-c${round}"
  cp "$ROOT/logs/evals/latest.md" "$LOGDIR/M4-c${round}.md" 2>/dev/null || true
done

mtplx stop --port 8000 2>/dev/null || true
echo "=== Stage 2 confirmation complete ==="
summarize_confirmation
echo "Next: stage3-full.sh for full L1 + top two (+ auto Stage 4)."
