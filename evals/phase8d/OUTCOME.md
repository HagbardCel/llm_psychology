# Phase 8D — synthetic patient cost benchmark outcome

## Environment / provenance

- **Source branch:** `refactor/phase-8-lean-closure` (implementation PR merged locally; live experiment pending operator)
- **Benchmark module:** `evals/phase8d/patient_benchmark.py`
- **Product/session LLM:** not configured for timed live runs in this closure step
- **P2 candidate (named upfront):** Gemma4-E4B at operator-chosen `--patient-base-url` / `--patient-model`
- **Blocked reason:** mandatory live patient endpoint (P0/P1 on production Jung LLM settings) unavailable in the automated closure environment (no GPU/local inference server)

## Local raw evidence

| Artifact | Status |
| --- | --- |
| `logs/phase8d/run-<UTC-1>/benchmark.json` (mandatory P0/P1) | **not created** |
| `logs/phase8d/run-<UTC-2>/benchmark.json` (optional P2) | **not created** |

## P0 result (totals + A/B/C/D quality)

**Not run.** No balanced P0/P1 invocation was executed.

## P1 result

**Not run.**

## P2 result

**Not run** (P2 escalation not reached; Gemma4-E4B candidate named but not exercised).

## Selected patient configuration

No arm selected. Reproduce the benchmark when endpoints are available:

```bash
# P0/P1 (8 balanced calls)
uv run --locked python -m evals.phase8d.patient_benchmark run-p0-p1

# P2 (4 calls, only if escalated after P0/P1 quality/latency review)
uv run --locked python -m evals.phase8d.patient_benchmark run-p2 \
  --patient-base-url http://127.0.0.1:8081/v1 \
  --patient-model gemma4-e4b
```

If P1 wins, adopt for simulation via generic flags (example — adjust to measured session `extra_body`):

```bash
make simulate-local-llm \
  SIM_ARGS="--scenario social_anxiety --sessions 3 --turns-per-session 8 \
  --patient-extra-body-json '{\"chat_template_kwargs\":{\"enable_thinking\":false}}'"
```

If P2 wins, adopt via `--patient-base-url` / `--patient-model` instead. Do not hard-code winners into `SimulationConfig` defaults.

## Selected configuration

**None** (live benchmark not executed).

## Canary

**Not run.** Mandatory integration canary (1 session × 2 turns with selected patient flags) was not executed because no arm was selected.

## Decision

Phase 8D live evidence is incomplete. Implementation deliverables (benchmark tooling, `--patient-extra-body-json`, `patient_metrics`) are merged; operational patient-cost selection awaits operator execution of the live protocol in [`README.md`](README.md).

## Status

**NOT RUN / BLOCKED**
