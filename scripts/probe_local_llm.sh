#!/usr/bin/env bash
set -u

cd "$(dirname "$0")/.."

scenario=first_session_smoke
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
run_name="${timestamp}_${scenario}"
run_dir="logs/workflow-probes/${run_name}"
compose=(docker compose -f docker-compose.yml -f docker-compose.probe.yml)

mkdir -p "$run_dir"
chmod -R a+rwX logs/workflow-probes
export HOST_UID="$(id -u)"
export HOST_GID="$(id -g)"
export PROBE_RUN_NAME="$run_name"

cleanup() {
  local exit_code=$?

  chmod -R a+rwX logs/workflow-probes 2>/dev/null || true

  publish_latest "$run_name" latest || true
  publish_latest "$run_name/trace.jsonl" latest.jsonl || true
  publish_latest "$run_name/summary.md" latest.md || true
  publish_latest "$run_name/created_rows.json" latest_db_export.json || true
  publish_latest "$run_name/run_manifest.json" latest_manifest.json || true
  "${compose[@]}" stop api-probe >/dev/null 2>&1 || true
  exit "$exit_code"
}

publish_latest() {
  local target=$1
  local name=$2

  if [ ! -e "logs/workflow-probes/$target" ]; then
    return 0
  fi

  ln -sfn "$target" "logs/workflow-probes/${name}.tmp"
  if mv -Tf "logs/workflow-probes/${name}.tmp" "logs/workflow-probes/${name}" 2>/dev/null; then
    return 0
  fi
  if mv -fh "logs/workflow-probes/${name}.tmp" "logs/workflow-probes/${name}" 2>/dev/null; then
    return 0
  fi
  rm -f "logs/workflow-probes/${name}"
  mv -f "logs/workflow-probes/${name}.tmp" "logs/workflow-probes/${name}"
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
