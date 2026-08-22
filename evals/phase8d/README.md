# Phase 8D — synthetic patient cost benchmark

Phase-local diagnostic tooling. **Not a permanent eval gate.**

This benchmark compares patient inference cost for three arms:

| Arm | Description |
| --- | --- |
| P0 | Implicit patient endpoint; no patient `extra_body` override |
| P1 | Same endpoint/model; complete patient `extra_body` with thinking disabled |
| P2 | Separate cheap patient endpoint (frozen candidate: locally served **Gemma4-E4B**) |

## Live protocol

1. Ensure product/session and (if used) P2 patient endpoints are loaded and responsive.
2. Name P2 upfront: Gemma4-E4B `--patient-base-url` / `--patient-model` (or record P2 unavailable).
3. Run balanced P0/P1 (8 calls): `P0-A P1-A P0-B P1-B P1-C P0-C P1-D P0-D`.
4. Human quality check per context (A–D) per arm.
5. If P1 passes quality and total latency ≤ 90% of P0 → select P1 and stop.
6. Otherwise run P2 (4 calls) only if Gemma4-E4B was named upfront.
7. If P2 passes quality and total latency ≤ 85% of P0 → select P2; else P0.
8. One short `simulate-local-llm` canary with the selected flags (post-merge).

Do not add repetitions, retries, or sample chasing near thresholds.

## Artifacts

Each invocation writes one gitignored file:

```text
logs/phase8d/run-<UTC>/benchmark.json
```

P0/P1 share one invocation; P2 uses a separate invocation if escalated.

Record human quality and the operational decision in post-merge
[`OUTCOME.md`](OUTCOME.md) (added after the live experiment).

## Run (operator)

Uses production Jung LLM settings (`LLM_BASE_URL`, `MODEL_NAME`, …):

```bash
uv run --locked python -m evals.phase8d.patient_benchmark run-p0-p1
uv run --locked python -m evals.phase8d.patient_benchmark run-p2 \
  --patient-base-url http://127.0.0.1:8081/v1 \
  --patient-model gemma4-e4b
```

P2 flags are **not** hard-coded into generic simulation defaults.
