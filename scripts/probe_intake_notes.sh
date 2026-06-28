#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

scenario=intake_note_tracking
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
run_name="${timestamp}_${scenario}_deterministic"
run_dir="logs/workflow-probes/${run_name}"
compose=(docker compose -f docker-compose.yml -f docker-compose.probe.yml -f docker-compose.probe-intake-notes.yml)

mkdir -p logs logs/workflow-probes "$run_dir"
if [ "${CI:-}" = "true" ]; then
  chmod -R a+rwX logs
else
  chmod -R u+rwX,g+rwX logs
fi

export HOST_UID="$(id -u)"
export HOST_GID="$(id -g)"
export PROBE_RUN_NAME="$run_name"

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

cleanup() {
  local exit_code=$?

  chmod -R a+rwX logs/workflow-probes 2>/dev/null || true

  publish_latest "$run_name" latest-intake-notes || true
  publish_latest "$run_name/trace.jsonl" latest-intake-notes.jsonl || true
  publish_latest "$run_name/summary.md" latest-intake-notes.md || true
  publish_latest "$run_name/created_rows.json" latest-intake-notes_db_export.json || true
  publish_latest "$run_name/run_manifest.json" latest-intake-notes_manifest.json || true
  publish_latest "$run_name/intake_note_tracking.json" latest-intake-notes_diagnostics.json || true

  "${compose[@]}" stop api-probe >/dev/null 2>&1 || true
  exit "$exit_code"
}
trap cleanup EXIT

"${compose[@]}" up --build --remove-orphans -d --wait api-probe
exit_code=0
"${compose[@]}" run --rm --build --no-deps console-probe-runner || exit_code=$?

if [ "$exit_code" -ne 0 ] && [ -f "$run_dir/failure_summary.md" ]; then
  printf '\nIntake note tracking probe failure summary:\n'
  sed -n '1,80p' "$run_dir/failure_summary.md"
fi

if [ -f "$run_dir/intake_note_tracking.json" ]; then
  printf '\nIntake note tracking diagnostics:\n'
  sed -n '1,120p' "$run_dir/intake_note_tracking.json"
fi

exit "$exit_code"
