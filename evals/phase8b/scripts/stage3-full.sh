#!/bin/bash
# Phase 8B Stage 3 (+ conditional Stage 4) — full workload validation.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"
phase8b_common_init

decide_and_run_stage4() {
  python3 - <<PY >"$LOGDIR/stage3-decision.json"
import json, pathlib
logdir = pathlib.Path("$LOGDIR")

def wall(name):
    p = logdir / f"{name}.metrics.json"
    if not p.exists():
        return None
    m = json.loads(p.read_text())
    if m.get("workload") != "full":
        return None
    w = m.get("evaluation_wall_seconds")
    if w is None:
        return None
    return float(w)

m4 = wall("M4-full")
m1 = wall("M1-full")
screen_rank = ["M4", "M1"]
decision = {
    "l1_full": wall("L1-full"),
    "m4_full": m4,
    "m1_full": m1,
    "screen_rank": screen_rank,
    "stage4": False,
    "reason": "",
    "pair": [],
}
if m4 is None or m1 is None:
    decision["reason"] = "missing M4-full or M1-full; skip Stage 4"
else:
    full_rank = sorted([("M4", m4), ("M1", m1)], key=lambda x: x[1])
    decision["full_rank"] = [{"id": a, "wall": b} for a, b in full_rank]
    best, second = full_rank[0], full_rank[1]
    gap = (second[1] - best[1]) / best[1] if best[1] > 0 else 0.0
    decision["full_gap_vs_best"] = gap
    reverse = [a for a, _ in full_rank] != screen_rank
    close = gap < 0.10
    decision["ranking_reversed"] = reverse
    decision["within_10pct"] = close
    if reverse or close:
        decision["stage4"] = True
        decision["pair"] = [full_rank[0][0], full_rank[1][0]]
        reasons = []
        if reverse:
            reasons.append("screen/full ranking reversed")
        if close:
            reasons.append(f"full finalists within 10% (gap={gap:.1%})")
        decision["reason"] = "; ".join(reasons)
    else:
        decision["reason"] = f"no Stage 4: full gap={gap:.1%}, ranking matches screen"
print(json.dumps(decision, indent=2))
PY
  echo "=== Stage 3 decision ==="
  cat "$LOGDIR/stage3-decision.json"
  local need
  need=$(python3 -c 'import json;print("yes" if json.load(open("'"$LOGDIR/stage3-decision.json"'"))["stage4"] else "no")')
  if [[ "$need" != "yes" ]]; then
    echo "Stage 4 not required."
    return 0
  fi

  echo "=== Stage 4: extra alternating full pair ==="
  local first second n_first n_second
  first=$(python3 -c 'import json;print(json.load(open("'"$LOGDIR/stage3-decision.json"'"))["pair"][0])')
  second=$(python3 -c 'import json;print(json.load(open("'"$LOGDIR/stage3-decision.json"'"))["pair"][1])')
  [[ "$first" == "M4" ]] && n_first=4 || n_first=1
  [[ "$second" == "M4" ]] && n_second=4 || n_second=1

  run_mtplx_full_named() {
    local tag=$1
    local n=$2
    export_mtplx_smoke_env
    start_mtplx serial "$LOGDIR/mtplx-${tag}.log"
    preflight_json_schema http://127.0.0.1:8000/v1
    dummy_warm http://127.0.0.1:8000/v1
    run_eval_full "$n"
    record_metrics "$tag"
    cp "$ROOT/logs/evals/latest.md" "$LOGDIR/${tag}.md" 2>/dev/null || true
  }

  echo "=== Stage 4a: ${first}-full-s4a (N=$n_first) ==="
  run_mtplx_full_named "${first}-full-s4a" "$n_first"
  echo "=== Stage 4b: ${second}-full-s4b (N=$n_second) ==="
  run_mtplx_full_named "${second}-full-s4b" "$n_second"
}

print_final_walls() {
  python3 - <<PY
import json, pathlib
logdir = pathlib.Path("$LOGDIR")
print("=== Final Phase 8B full walls ===")
for name in ("L1-full", "M4-full", "M1-full", "M4-full-s4a", "M1-full-s4b"):
    p = logdir / f"{name}.metrics.json"
    if not p.exists():
        continue
    m = json.loads(p.read_text())
    wall = m.get("evaluation_wall_seconds")
    if wall is not None:
        print(f"{name}: wall={wall:.1f} workload={m.get('workload')} jobs={m.get('report_jobs')}")
    else:
        print(f"{name}: {m}")
PY
}

echo "=== Phase 8B Stage 3 full validation ==="
echo "Worksheet: $WORKSHEET"
RESUME="${PHASE8B_STAGE3_RESUME:-}"

if [[ "$RESUME" == "STAGE4" ]]; then
  echo "=== Resuming at Stage 4 (M4-full/M1-full must exist) ==="
  assert_metrics_resume_ok M4-full full 34
  assert_metrics_resume_ok M1-full full 34
  ensure_llguidance
  assert_mtplx_freeze
  export_mtplx_smoke_env
  decide_and_run_stage4
  mtplx stop --port 8000 2>/dev/null || true
  print_final_walls
  exit 0
fi

if [[ -z "$RESUME" || "$RESUME" == "L1" ]]; then
  echo "=== Stage 3: L1-full ==="
  export_llama_smoke_env
  export LOCAL_LLM_SMOKE_REQUEST_TIMEOUT=1800
  mtplx stop --port 8000 2>/dev/null || true
  start_llama 1 "$LOGDIR/llama-L1-full.log"
  dummy_warm http://127.0.0.1:8080/v1
  make smoke-local-llm | tee "$LOGDIR/smoke-llama-full.log" || {
    echo "WARNING: llama smoke failed; continuing to timed L1-full"
  }
  start_llama 1 "$LOGDIR/llama-L1-full.log"
  dummy_warm http://127.0.0.1:8080/v1
  if run_eval_full 1; then
    record_metrics L1-full
    cp "$ROOT/logs/evals/latest.md" "$LOGDIR/L1-full.md" 2>/dev/null || true
  else
    echo "WARNING: L1-full failed; continuing to MTPLX finalists"
    printf '%s\n' '{"status":"failed","workload":"full","concurrency":1,"error":"eval-report failed","server":"llama.cpp"}' \
      >"$LOGDIR/L1-full.metrics.json"
    echo "L1-full FAILED" >"$LOGDIR/L1-full.FAILED.txt"
  fi
  stop_llama
  RESUME=""
else
  echo "=== Skipping L1-full (PHASE8B_STAGE3_RESUME=$RESUME) ==="
fi

ensure_llguidance
assert_mtplx_freeze
export_mtplx_smoke_env
export LOCAL_LLM_SMOKE_REQUEST_TIMEOUT=600

if [[ -z "$RESUME" || "$RESUME" == "M4" ]]; then
  assert_metrics_resume_ok M4-full full 34
  echo "=== Stage 3: M4-full ==="
  start_mtplx serial "$LOGDIR/mtplx-M4-full-smoke.log"
  preflight_json_schema http://127.0.0.1:8000/v1
  dummy_warm http://127.0.0.1:8000/v1
  make smoke-local-llm | tee "$LOGDIR/smoke-mtplx-full.log" || {
    echo "WARNING: mtplx smoke failed; continuing to timed full rows"
  }
  start_mtplx serial "$LOGDIR/mtplx-M4-full.log"
  preflight_json_schema http://127.0.0.1:8000/v1
  dummy_warm http://127.0.0.1:8000/v1
  run_eval_full 4
  record_metrics M4-full
  cp "$ROOT/logs/evals/latest.md" "$LOGDIR/M4-full.md" 2>/dev/null || true
  RESUME=""
fi

if [[ -z "$RESUME" || "$RESUME" == "M1" ]]; then
  assert_metrics_resume_ok M1-full full 34
  echo "=== Stage 3: M1-full ==="
  start_mtplx serial "$LOGDIR/mtplx-M1-full.log"
  preflight_json_schema http://127.0.0.1:8000/v1
  dummy_warm http://127.0.0.1:8000/v1
  run_eval_full 1
  record_metrics M1-full
  cp "$ROOT/logs/evals/latest.md" "$LOGDIR/M1-full.md" 2>/dev/null || true
fi

echo "=== Stage 3 complete; evaluating Stage 4 trigger ==="
decide_and_run_stage4
mtplx stop --port 8000 2>/dev/null || true
stop_llama
print_final_walls
echo "Update evals/phase8b/OUTCOME.md if re-running; see tracked outcome for closed matrix."
