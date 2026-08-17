#!/bin/bash
# Shared Phase 8B operator helpers. Source from stage scripts only.
# Runtime output goes to gitignored logs/evals/phase8b/ — never under evals/phase8b/.
set -euo pipefail

phase8b_common_init() {
  local script_path="${BASH_SOURCE[1]:-${BASH_SOURCE[0]}}"
  PHASE8B_SCRIPT_DIR="$(cd "$(dirname "$script_path")" && pwd)"
  ROOT="$(cd "$PHASE8B_SCRIPT_DIR/../../.." && pwd)"
  LOGDIR="${PHASE8B_LOGDIR:-$ROOT/logs/evals/phase8b}"
  WORKSHEET="$LOGDIR/worksheet.md"
  cd "$ROOT"
  mkdir -p "$LOGDIR"

  LLAMA="${LLAMA_SERVER:-$HOME/experiments/llama.cpp/build/bin/llama-server}"
  GGUF="${GGUF_PATH:-$HOME/data/models/llm/gguf/lmstudio-community/Qwen3.8-27B-GGUF/Qwen3.8-27B-Q4_K_M.gguf}"
  MTPLX_MODEL="${MTPLX_MODEL:-Youssofal/Qwen3.8-27B-MTPLX-Optimized-Speed}"
  export MTPLX_BREW_VENV="${MTPLX_BREW_VENV:-/opt/homebrew/var/mtplx/venv-2.7.1}"
  MTPLX_PY="${MTPLX_PY:-$MTPLX_BREW_VENV/bin/python}"
  MTPLX_EXPECT_VERSION="${MTPLX_EXPECT_VERSION:-2.7.1}"

  export LOCAL_LLM_SMOKE_STRUCTURED_MODE=json_schema
  export LOCAL_LLM_SMOKE_EXTRA_BODY='{"chat_template_kwargs":{"enable_thinking":true},"top_p":0.95,"top_k":20}'
  DUMMY_PAYLOAD='{"model":"x","messages":[{"role":"user","content":"Say the word ready."}],"max_tokens":8,"temperature":0}'
}

assert_mtplx_freeze() {
  local ver
  ver=$(mtplx --version 2>&1 | head -1)
  echo "mtplx CLI: $ver (MTPLX_BREW_VENV=$MTPLX_BREW_VENV)"
  if ! printf '%s' "$ver" | grep -q "${MTPLX_EXPECT_VERSION//./\\.}"; then
    echo "Refusing to continue: expected mtplx $MTPLX_EXPECT_VERSION under $MTPLX_BREW_VENV, got: $ver"
    return 1
  fi
}

ensure_llguidance() {
  if ! "$MTPLX_PY" -c 'import importlib.metadata as md; md.version("llguidance")' 2>/dev/null; then
    echo "Refusing to continue: llguidance missing in $MTPLX_PY"
    echo "Install: $MTPLX_PY -m pip install 'llguidance>=1.7'"
    return 1
  fi
  "$MTPLX_PY" - <<'PY'
import importlib.metadata as md
import sys
print("MTPLX runtime:", sys.executable)
print("llguidance:", md.version("llguidance"))
print("mtplx:", md.version("mtplx"))
PY
}

# Refuse resume when an existing artifact implies a different workload/build.
assert_metrics_resume_ok() {
  local id=$1
  local expect_workload=$2
  local expect_jobs=$3
  local metrics="$LOGDIR/${id}.metrics.json"
  [[ -f "$metrics" ]] || return 0
  python3 - <<PY
import json, sys
p = "$metrics"
m = json.loads(open(p).read())
wl = m.get("workload")
jobs = m.get("report_jobs")
if wl is not None and wl != "$expect_workload":
    print(f"Refusing resume: {p} has workload={wl}, expected $expect_workload", file=sys.stderr)
    sys.exit(1)
if jobs is not None and jobs != $expect_jobs:
    print(f"Refusing resume: {p} has report_jobs={jobs}, expected $expect_jobs", file=sys.stderr)
    sys.exit(1)
if m.get("status") == "failed" and "$expect_workload" == "full" and "full" in "$id":
    pass  # L1-full failure is allowed; caller decides skip vs retry
PY
}

preflight_json_schema() {
  local base=$1
  local model
  model=$(curl -s -m 5 "$base/models" | python3 -c 'import sys,json; print(json.load(sys.stdin)["data"][0]["id"])')
  local body
  body=$(python3 - <<PY
import json
print(json.dumps({
  "model": "$model",
  "messages": [{"role": "user", "content": "Reply with {\\"ok\\": true} only."}],
  "max_tokens": 32,
  "temperature": 0,
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "ok",
      "schema": {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
      },
      "strict": True,
    },
  },
}))
PY
)
  local resp http payload
  resp=$(curl -s -m 120 -w '\n%{http_code}' "$base/chat/completions" \
    -H 'Content-Type: application/json' \
    -d "$body")
  http=$(printf '%s' "$resp" | tail -n1)
  payload=$(printf '%s' "$resp" | sed '$d')
  printf '%s\n' "$payload" >"$LOGDIR/json-schema-preflight.json"
  if [[ "$http" != "200" ]] || printf '%s' "$payload" | grep -qi 'llguidance'; then
    echo "json_schema preflight FAILED (HTTP $http)"
    return 1
  fi
  echo "json_schema preflight OK (HTTP $http)"
}

dummy_warm() {
  local base=$1
  curl -s -m 120 "$base/chat/completions" \
    -H 'Content-Type: application/json' \
    -d "${DUMMY_PAYLOAD/x/$(curl -s "$base/models" | python3 -c 'import sys,json; print(json.load(sys.stdin)["data"][0]["id"])')}" \
    >"$LOGDIR/dummy-warm.json" || true
}

record_metrics() {
  local id=$1
  python3 - <<PY
import json, pathlib
root = pathlib.Path("$ROOT")
p = root / "logs/evals/latest.metrics.json"
out = pathlib.Path("$LOGDIR") / "$id.metrics.json"
if not p.exists():
    print("$id: no metrics sidecar")
else:
    m = json.loads(p.read_text())
    print(
        f"$id wall={m.get('evaluation_wall_seconds')} "
        f"workload={m.get('workload')} report_jobs={m.get('report_jobs')} "
        f"overlap={m.get('request_overlap_factor')} attempts={m.get('provider_attempts')} "
        f"corrections={m.get('correction_attempts')}"
    )
    out.write_text(json.dumps(m, indent=2))
PY
}

start_mtplx() {
  local mode=$1
  local log=$2
  assert_mtplx_freeze
  mtplx stop --port 8000 2>/dev/null || true
  sleep 2
  mtplx serve \
    --model "$MTPLX_MODEL" \
    --scheduler-mode "$mode" \
    --ssd-session-cache off \
    --reasoning on \
    --reasoning-effort medium \
    --default-top-p 0.95 \
    --default-top-k 20 \
    --host 127.0.0.1 \
    --port 8000 \
    --no-auth \
    >"$log" 2>&1 &
  echo $! >"$LOGDIR/mtplx.pid"
  local wait_i
  for wait_i in $(seq 1 90); do
    if curl -s -m 2 http://127.0.0.1:8000/health | grep -q '"ok":true\|"ok": true'; then
      if head -n 40 "$log" | grep -q 'MTPLX 2\.7\.0'; then
        echo "Abort: server log shows MTPLX 2.7.0"
        return 1
      fi
      if ! head -n 40 "$log" | grep -q "MTPLX ${MTPLX_EXPECT_VERSION}"; then
        echo "Abort: server log missing MTPLX $MTPLX_EXPECT_VERSION banner"
        return 1
      fi
      echo "MTPLX ready ($mode) after ${wait_i}s"
      return 0
    fi
    sleep 2
  done
  echo "MTPLX failed to become ready"
  return 1
}

start_llama() {
  local n=$1
  local ctx=$((32768 * n))
  local log=$2
  if [[ ! -x "$LLAMA" ]]; then
    echo "Refusing to continue: llama-server not found at LLAMA_SERVER=$LLAMA"
    return 1
  fi
  if [[ ! -f "$GGUF" ]]; then
    echo "Refusing to continue: GGUF not found at GGUF_PATH=$GGUF"
    return 1
  fi
  if [[ -f "$LOGDIR/llama.pid" ]]; then
    kill "$(cat "$LOGDIR/llama.pid")" 2>/dev/null || true
    sleep 2
  fi
  "$LLAMA" -m "$GGUF" \
    --host 127.0.0.1 --port 8080 \
    --ctx-size "$ctx" --parallel "$n" \
    --cont-batching --min-p 0 --jinja \
    >"$log" 2>&1 &
  echo $! >"$LOGDIR/llama.pid"
  local wait_i
  for wait_i in $(seq 1 90); do
    if curl -s -m 2 http://127.0.0.1:8080/props | grep -q total_slots; then
      echo "llama ready (parallel=$n ctx=$ctx) after ${wait_i}s"
      curl -s http://127.0.0.1:8080/props | python3 -c 'import sys,json;p=json.load(sys.stdin);print("slots",p.get("total_slots"),"path",p.get("model_path"),"build",p.get("build_info"))'
      return 0
    fi
    sleep 2
  done
  echo "llama failed to become ready"
  return 1
}

stop_llama() {
  if [[ -f "$LOGDIR/llama.pid" ]]; then
    kill "$(cat "$LOGDIR/llama.pid")" 2>/dev/null || true
    rm -f "$LOGDIR/llama.pid"
    sleep 2
  fi
}

run_eval_screen() {
  local n=$1
  make eval-report EVAL_REPORT_ARGS="--workload screen --concurrency $n"
}

run_eval_full() {
  local n=$1
  make eval-report EVAL_REPORT_ARGS="--workload full --concurrency $n"
}

export_mtplx_smoke_env() {
  export LOCAL_LLM_SMOKE_BASE_URL=http://127.0.0.1:8000/v1
  export LOCAL_LLM_SMOKE_MODEL=mtplx-qwen38-27b-optimized-speed
  export LOCAL_LLM_SMOKE_SERVER=mtplx
  export LOCAL_LLM_SMOKE_SERVER_VERSION="$MTPLX_EXPECT_VERSION"
  export LOCAL_LLM_SMOKE_REQUEST_TIMEOUT="${LOCAL_LLM_SMOKE_REQUEST_TIMEOUT:-600}"
}

export_llama_smoke_env() {
  export LOCAL_LLM_SMOKE_BASE_URL=http://127.0.0.1:8080/v1
  export LOCAL_LLM_SMOKE_MODEL=Qwen3.8-27B-Q4_K_M
  export LOCAL_LLM_SMOKE_SERVER=llama.cpp
  export LOCAL_LLM_SMOKE_SERVER_VERSION="${LLAMA_BUILD_ID:-b10428-885c5bbe8}"
  export LOCAL_LLM_SMOKE_REQUEST_TIMEOUT="${LOCAL_LLM_SMOKE_REQUEST_TIMEOUT:-600}"
}
