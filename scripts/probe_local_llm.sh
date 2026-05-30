#!/usr/bin/env bash
set -u

cd "$(dirname "$0")/.."

scenario=first_session_smoke
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
run_name="${timestamp}_${scenario}"
run_dir="logs/workflow-probes/${run_name}"
compose=(docker compose -f docker-compose.yml -f docker-compose.probe.yml)

mkdir -p "$run_dir"
export PROBE_RUN_NAME="$run_name"

cleanup() {
  local exit_code=$?
  ln -sfn "$run_name" logs/workflow-probes/latest
  "${compose[@]}" stop api-probe >/dev/null 2>&1 || true
  exit "$exit_code"
}
trap cleanup EXIT

"${compose[@]}" up --build --remove-orphans -d --wait api-probe
"${compose[@]}" run --rm --build --no-deps console-probe-runner
