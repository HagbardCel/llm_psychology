#!/usr/bin/env bash
set -u

cd "$(dirname "$0")/.."

scenario=first_session_smoke
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
run_name="${timestamp}_${scenario}_deterministic"
run_dir="logs/workflow-probes/${run_name}"
compose=(docker compose -f docker-compose.yml -f docker-compose.probe.yml -f docker-compose.probe-deterministic.yml)

mkdir -p "$run_dir"
export PROBE_RUN_NAME="$run_name"

publish_latest() {
  local target=$1
  local name=$2
  ln -sfn "$target" "logs/workflow-probes/${name}.tmp"
  if mv -Tf "logs/workflow-probes/${name}.tmp" "logs/workflow-probes/${name}" 2>/dev/null; then
    return
  fi
  if mv -fh "logs/workflow-probes/${name}.tmp" "logs/workflow-probes/${name}" 2>/dev/null; then
    return
  fi
  rm -f "logs/workflow-probes/${name}"
  mv -f "logs/workflow-probes/${name}.tmp" "logs/workflow-probes/${name}"
}

cleanup() {
  local exit_code=$?
  publish_latest "$run_name" latest
  publish_latest "$run_name/trace.jsonl" latest.jsonl
  publish_latest "$run_name/summary.md" latest.md
  publish_latest "$run_name/created_rows.json" latest_db_export.json
  publish_latest "$run_name/run_manifest.json" latest_manifest.json
  "${compose[@]}" stop api-probe >/dev/null 2>&1 || true
  exit "$exit_code"
}
trap cleanup EXIT

"${compose[@]}" up --build --remove-orphans -d --wait api-probe
"${compose[@]}" run --rm --build --no-deps console-probe-runner
exit_code=$?
if [ "$exit_code" -ne 0 ] && [ -f "$run_dir/failure_summary.md" ]; then
  printf '\nProbe failure summary:\n'
  sed -n '1,80p' "$run_dir/failure_summary.md"
fi
exit "$exit_code"
