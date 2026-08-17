#!/bin/bash
# Shared Phase 8B operator helpers. Source from stage scripts only.
# Runtime output goes to gitignored logs/evals/phase8b/ — never under evals/phase8b/.
set -euo pipefail

LLAMA_PORT=8080
MTPLX_PORT=8000
PER_SLOT_CTX=32768

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
  MTPLX_BIN="${MTPLX_BIN:-$MTPLX_BREW_VENV/bin/mtplx}"
  MTPLX_PY="${MTPLX_PY:-$MTPLX_BREW_VENV/bin/python}"
  export MTPLX_BIN
  MTPLX_EXPECT_VERSION="${MTPLX_EXPECT_VERSION:-2.7.1}"
  LLAMA_BUILD_ID="${LLAMA_BUILD_ID:-b10428-885c5bbe8}"
  FIXTURE_MANIFEST="$LOGDIR/fixture-manifest.json"

  export LOCAL_LLM_SMOKE_STRUCTURED_MODE=json_schema
  export LOCAL_LLM_SMOKE_EXTRA_BODY='{"chat_template_kwargs":{"enable_thinking":true},"top_p":0.95,"top_k":20}'
  DUMMY_PAYLOAD='{"model":"x","messages":[{"role":"user","content":"Say the word ready."}],"max_tokens":8,"temperature":0}'
}

release_phase8b_lock() {
  if [[ -n "${LOCKDIR:-}" ]]; then
    rmdir "$LOCKDIR" 2>/dev/null || true
  fi
}

acquire_phase8b_lock() {
  LOCKDIR="$LOGDIR/.lock"
  if ! mkdir "$LOCKDIR" 2>/dev/null; then
    echo "Another Phase 8B run holds $LOCKDIR"
    echo "Remove .lock manually after verifying no Phase 8B script is running."
    exit 1
  fi
  trap release_phase8b_lock EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
}

assert_clean_worktree() {
  if [[ -n "$(git status --porcelain --untracked-files=normal)" ]]; then
    echo "Refusing Phase 8B benchmark: working tree is dirty."
    echo "Commit/stash changes first so source_revision identifies the executed code."
    exit 1
  fi
}

write_fixture_manifest() {
  assert_clean_worktree
  local revision
  revision=$(git rev-parse HEAD)
  python3 - <<PY
import json, pathlib
manifest = {
    "schema": "phase8b-fixture-v1",
    "source_revision": "$revision",
    "mtplx_version": "$MTPLX_EXPECT_VERSION",
    "mtplx_model": "$MTPLX_MODEL",
    "mtplx_bin": "$MTPLX_BIN",
    "llama_build": "$LLAMA_BUILD_ID",
    "gguf_path": "$GGUF",
    "structured_mode": "json_schema",
    "smoke_extra_body": '{"chat_template_kwargs":{"enable_thinking":true},"top_p":0.95,"top_k":20}',
    "request_timeout": 600,
    "per_slot_ctx": $PER_SLOT_CTX,
}
pathlib.Path("$FIXTURE_MANIFEST").write_text(json.dumps(manifest, indent=2) + "\n")
print(f"Wrote fixture manifest: $FIXTURE_MANIFEST")
PY
}

assert_fixture_resume_ok() {
  if [[ ! -f "$FIXTURE_MANIFEST" ]]; then
    if compgen -G "$LOGDIR/*.metrics.json" >/dev/null; then
      echo "Refusing to initialize a fixture manifest over existing benchmark artifacts."
      echo "Use a fresh PHASE8B_LOGDIR or archive/remove the old artifacts."
      exit 1
    fi
    write_fixture_manifest
    return 0
  fi
  assert_clean_worktree
  local revision
  revision=$(git rev-parse HEAD)
  python3 - <<PY
import json, pathlib, sys
expected = {
    "schema": "phase8b-fixture-v1",
    "source_revision": "$revision",
    "mtplx_version": "$MTPLX_EXPECT_VERSION",
    "mtplx_model": "$MTPLX_MODEL",
    "mtplx_bin": "$MTPLX_BIN",
    "llama_build": "$LLAMA_BUILD_ID",
    "gguf_path": "$GGUF",
    "structured_mode": "json_schema",
    "smoke_extra_body": '{"chat_template_kwargs":{"enable_thinking":true},"top_p":0.95,"top_k":20}',
    "request_timeout": 600,
    "per_slot_ctx": $PER_SLOT_CTX,
}
path = pathlib.Path("$FIXTURE_MANIFEST")
existing = json.loads(path.read_text())
for key, value in expected.items():
    if existing.get(key) != value:
        print(
            f"Refusing resume: fixture-manifest {key}={existing.get(key)!r}, expected {value!r}",
            file=sys.stderr,
        )
        sys.exit(1)
PY
}

validate_stage1_resume() {
  local resume=${1:-}
  [[ -z "$resume" ]] && return 0
  case "$resume" in
    M1 | M4 | A2 | A4 | T4 | L1) return 0 ;;
    *)
      echo "Invalid PHASE8B_RESUME=$resume (valid: M1 M4 A2 A4 T4 L1)"
      exit 1
      ;;
  esac
}

validate_stage3_resume() {
  local resume=${1:-}
  [[ -z "$resume" ]] && return 0
  case "$resume" in
    L1 | M4 | M1 | STAGE4) return 0 ;;
    *)
      echo "Invalid PHASE8B_STAGE3_RESUME=$resume (valid: L1 M4 M1 STAGE4)"
      exit 1
      ;;
  esac
}

_mtpx_cli_version() {
  "$MTPLX_BIN" --version 2>&1 | head -1 | sed -E 's/^[^0-9]*([0-9]+\.[0-9]+\.[0-9]+).*/\1/'
}

assert_mtplx_freeze() {
  if [[ ! -x "$MTPLX_BIN" ]]; then
    echo "Refusing to continue: MTPLX_BIN not executable: $MTPLX_BIN"
    return 1
  fi
  local meta_ver cli_ver
  meta_ver=$("$MTPLX_PY" -c 'import importlib.metadata as md; print(md.version("mtplx"))')
  cli_ver=$(_mtpx_cli_version)
  echo "mtplx metadata: $meta_ver CLI: $cli_ver (MTPLX_BIN=$MTPLX_BIN)"
  if [[ "$meta_ver" != "$MTPLX_EXPECT_VERSION" ]]; then
    echo "Refusing to continue: expected mtplx metadata $MTPLX_EXPECT_VERSION, got: $meta_ver"
    return 1
  fi
  if [[ "$cli_ver" != "$MTPLX_EXPECT_VERSION" ]]; then
    echo "Refusing to continue: expected mtplx CLI $MTPLX_EXPECT_VERSION, got: $cli_ver"
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

run_smoke_gate() {
  local log=$1
  make smoke-local-llm | tee "$log"
}

record_compatibility_failure() {
  local id=$1
  local backend=$2
  local log=$3
  printf '%s\n' \
    "compatibility failure: $id ($backend) — smoke gate failed; see $log" \
    >"$LOGDIR/${id}.COMPAT-FAIL.txt"
  echo "$id: compatibility failure recorded ($backend smoke gate failed)"
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

_llama_port_listener_pid() {
  lsof -nP -iTCP:"$LLAMA_PORT" -sTCP:LISTEN -t 2>/dev/null | head -1
}

_wait_llama_port_free() {
  local wait_i
  for wait_i in $(seq 1 15); do
    if [[ -z "$(_llama_port_listener_pid)" ]]; then
      return 0
    fi
    sleep 1
  done
  return 1
}

_prepare_llama_port() {
  local listener recorded
  listener=$(_llama_port_listener_pid)
  if [[ -z "$listener" ]]; then
    rm -f "$LOGDIR/llama.pid"
    return 0
  fi
  if [[ -f "$LOGDIR/llama.pid" ]]; then
    recorded=$(cat "$LOGDIR/llama.pid")
    if [[ "$listener" == "$recorded" ]]; then
      kill "$listener" 2>/dev/null || true
      if ! _wait_llama_port_free; then
        echo "Refusing to continue: port $LLAMA_PORT still occupied after stopping harness PID $recorded"
        return 1
      fi
      rm -f "$LOGDIR/llama.pid"
      return 0
    fi
  fi
  echo "Refusing to continue: port $LLAMA_PORT occupied by PID $listener (not harness-owned)"
  return 1
}

verify_llama_server() {
  local n=$1
  local spawned_pid=$2
  if ! kill -0 "$spawned_pid" 2>/dev/null; then
    echo "Refusing to continue: llama-server PID $spawned_pid is not alive"
    return 1
  fi
  local listener
  listener=$(_llama_port_listener_pid)
  if [[ "$listener" != "$spawned_pid" ]]; then
    echo "Refusing to continue: port $LLAMA_PORT listener PID=$listener, expected spawned PID=$spawned_pid"
    return 1
  fi
  python3 - <<PY
import json, os, sys, urllib.request

n = int("$n")
expected_gguf = os.path.realpath("$GGUF")
expected_build = "$LLAMA_BUILD_ID"
per_slot = $PER_SLOT_CTX

props = json.loads(urllib.request.urlopen("http://127.0.0.1:$LLAMA_PORT/props", timeout=5).read())
slots_resp = json.loads(urllib.request.urlopen("http://127.0.0.1:$LLAMA_PORT/slots", timeout=5).read())

total = props.get("total_slots")
if total != n:
    print(f"Refusing to continue: total_slots={total}, expected {n}", file=sys.stderr)
    sys.exit(1)

model_path = props.get("model_path")
if not model_path:
    print("Refusing to continue: /props missing model_path", file=sys.stderr)
    sys.exit(1)
if os.path.realpath(model_path) != expected_gguf:
    print(
        f"Refusing to continue: model_path={model_path!r} != expected GGUF {expected_gguf!r}",
        file=sys.stderr,
    )
    sys.exit(1)

build = props.get("build_info") or ""
if expected_build not in build:
    print(f"Refusing to continue: build_info={build!r} missing {expected_build!r}", file=sys.stderr)
    sys.exit(1)

slots = slots_resp if isinstance(slots_resp, list) else slots_resp.get("slots", [])
if len(slots) != n:
    print(f"Refusing to continue: /slots count={len(slots)}, expected {n}", file=sys.stderr)
    sys.exit(1)
for i, slot in enumerate(slots):
    n_ctx = slot.get("n_ctx")
    if n_ctx != per_slot:
        print(f"Refusing to continue: slot {i} n_ctx={n_ctx}, expected {per_slot}", file=sys.stderr)
        sys.exit(1)

print(f"llama verified: parallel={n} model={model_path} build={build} slots={len(slots)} n_ctx={per_slot}")
PY
}

start_llama() {
  local n=$1
  local ctx=$((PER_SLOT_CTX * n))
  local log=$2
  if [[ ! -x "$LLAMA" ]]; then
    echo "Refusing to continue: llama-server not found at LLAMA_SERVER=$LLAMA"
    return 1
  fi
  if [[ ! -f "$GGUF" ]]; then
    echo "Refusing to continue: GGUF not found at GGUF_PATH=$GGUF"
    return 1
  fi
  _prepare_llama_port || return 1
  "$LLAMA" -m "$GGUF" \
    --host 127.0.0.1 --port "$LLAMA_PORT" \
    --ctx-size "$ctx" --parallel "$n" \
    --cont-batching --min-p 0 --jinja \
    >"$log" 2>&1 &
  local spawned_pid=$!
  echo "$spawned_pid" >"$LOGDIR/llama.pid"
  local wait_i
  for wait_i in $(seq 1 90); do
    if curl -s -m 2 "http://127.0.0.1:$LLAMA_PORT/props" | grep -q total_slots; then
      echo "llama ready (parallel=$n ctx=$ctx) after ${wait_i}s"
      verify_llama_server "$n" "$spawned_pid" || return 1
      return 0
    fi
    if ! kill -0 "$spawned_pid" 2>/dev/null; then
      echo "llama failed: spawned PID $spawned_pid exited before readiness"
      return 1
    fi
    sleep 2
  done
  echo "llama failed to become ready"
  return 1
}

stop_llama() {
  local listener recorded
  if [[ -f "$LOGDIR/llama.pid" ]]; then
    recorded=$(cat "$LOGDIR/llama.pid")
    listener=$(_llama_port_listener_pid)
    if [[ -n "$listener" && "$listener" == "$recorded" ]]; then
      kill "$listener" 2>/dev/null || true
    elif [[ -n "$listener" ]]; then
      echo "WARNING: port $LLAMA_PORT listener PID $listener != recorded harness PID $recorded; not killing"
    fi
    rm -f "$LOGDIR/llama.pid"
    sleep 2
  fi
  if [[ -n "$(_llama_port_listener_pid)" ]]; then
    echo "WARNING: port $LLAMA_PORT still occupied after stop_llama"
  fi
}

stop_mtplx() {
  "$MTPLX_BIN" stop --port "$MTPLX_PORT" 2>/dev/null || true
  sleep 2
}

start_mtplx() {
  local mode=$1
  local log=$2
  assert_mtplx_freeze
  stop_mtplx
  "$MTPLX_BIN" serve \
    --model "$MTPLX_MODEL" \
    --scheduler-mode "$mode" \
    --ssd-session-cache off \
    --reasoning on \
    --reasoning-effort medium \
    --default-top-p 0.95 \
    --default-top-k 20 \
    --host 127.0.0.1 \
    --port "$MTPLX_PORT" \
    --no-auth \
    >"$log" 2>&1 &
  echo $! >"$LOGDIR/mtplx.pid"
  local wait_i
  for wait_i in $(seq 1 90); do
    if curl -s -m 2 "http://127.0.0.1:$MTPLX_PORT/health" | grep -q '"ok":true\|"ok": true'; then
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

run_eval_screen() {
  local n=$1
  make eval-report EVAL_REPORT_ARGS="--workload screen --concurrency $n"
}

run_eval_full() {
  local n=$1
  make eval-report EVAL_REPORT_ARGS="--workload full --concurrency $n"
}

export_mtplx_smoke_env() {
  export LOCAL_LLM_SMOKE_BASE_URL="http://127.0.0.1:$MTPLX_PORT/v1"
  export LOCAL_LLM_SMOKE_MODEL=mtplx-qwen38-27b-optimized-speed
  export LOCAL_LLM_SMOKE_SERVER=mtplx
  export LOCAL_LLM_SMOKE_SERVER_VERSION="$MTPLX_EXPECT_VERSION"
  export LOCAL_LLM_SMOKE_REQUEST_TIMEOUT="${LOCAL_LLM_SMOKE_REQUEST_TIMEOUT:-600}"
}

export_llama_smoke_env() {
  export LOCAL_LLM_SMOKE_BASE_URL="http://127.0.0.1:$LLAMA_PORT/v1"
  export LOCAL_LLM_SMOKE_MODEL=Qwen3.8-27B-Q4_K_M
  export LOCAL_LLM_SMOKE_SERVER=llama.cpp
  export LOCAL_LLM_SMOKE_SERVER_VERSION="$LLAMA_BUILD_ID"
  export LOCAL_LLM_SMOKE_REQUEST_TIMEOUT="${LOCAL_LLM_SMOKE_REQUEST_TIMEOUT:-600}"
}

phase8b_bootstrap() {
  acquire_phase8b_lock
  assert_fixture_resume_ok
}
