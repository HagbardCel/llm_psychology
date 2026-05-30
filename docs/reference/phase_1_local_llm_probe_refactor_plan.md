---
owner: engineering
status: active
last_reviewed: 2026-05-30
review_cycle_days: 90
source_of_truth_for: Local full-stack workflow probe
---

# Phase 1 Local Workflow Probe Refactor

## Decision

Keep one optional full-stack diagnostic probe:

```bash
make probe
```

It starts an isolated backend and the real WebSocket console workflow. Both the
application agents and simulated patient use the same local OpenAI-compatible
endpoint configured by `LLM_BASE_URL`, `MODEL_NAME`, and optional `LLM_API_KEY`.

Deterministic correctness remains in pytest and E2E suites. The probe is not a
CI gate.

## Structure

Probe code lives under `console-ui/src/workflow_probe/`. `ConsoleClient` retains
generic `InputProvider` and `ConsoleEventSink` hooks, while the package owns
local-user generation, transcript recording, assertions, watchdog supervision,
and SQLite snapshots.

The only scenario is:

```text
console-ui/scenarios/workflow-probes/first_session_smoke.json
```

## Artifacts

Each run creates `logs/workflow-probes/<timestamp>_first_session_smoke/` with:

```text
summary.md
trace.jsonl
transcript.md
metadata.json
db_snapshot.sqlite
created_rows.json
```

`logs/workflow-probes/latest` points at the most recent run even when it fails.

## Commands

```bash
make probe
make probe-logs
make probe-db
```

For endpoint-only troubleshooting, run the unadvertised runner option:

```bash
docker compose -f docker-compose.yml -f docker-compose.probe.yml run --rm \
  console-probe-runner python -m src.workflow_probe.runner --check-local-llm
```
