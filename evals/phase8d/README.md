# Phase 8D — synthetic patient cost benchmark

Phase-local diagnostic tooling. **Not a permanent eval gate.**

This benchmark compares patient inference cost for three arms:

| Arm | Description |
| --- | --- |
| P0 | Implicit patient endpoint; no patient `extra_body` override |
| P1 | Same endpoint/model; complete patient `extra_body` with thinking disabled |
| P2 | Separate cheap patient endpoint (operator-named candidate) |

## Live protocol

1. Ensure product/session and (if used) P2 patient endpoints are loaded and responsive.
2. If P2 may be escalated, name the candidate upfront on the P0/P1 invocation via
   `--p2-candidate`. If `--p2-candidate` is omitted, P2 is not applicable for that
   experiment and must not be selected after inspecting P0/P1 results.
3. Run balanced P0/P1 (8 calls): `P0-A P1-A P0-B P1-B P1-C P0-C P1-D P0-D`.
4. Human quality check per context (A–D) per arm. Quality is a binary human
   review: first-person patient voice, no meta/reasoning leakage, consistency with
   the supplied history, and a plausible patient utterance. Do not use an LLM
   judge. Record PASS/FAIL per context per arm; add a short note only when
   needed.
5. If P1 passes quality and total latency ≤ 90% of P0 → select P1 and stop.
6. Otherwise run P2 (4 calls) only if a candidate was named upfront on step 2.
7. If P2 passes quality and total latency ≤ 85% of P0 → select P2; else P0.
8. Run exactly one whole-product canary with `--sessions 1 --turns-per-session 2`.
   This is an integration check, not a performance benchmark (post-merge).

Do not add repetitions, retries, or sample chasing near thresholds.

## Artifacts

Each invocation writes one gitignored file:

```text
logs/phase8d/run-<UTC>/benchmark.json
```

P0/P1 share one invocation; P2 uses a separate invocation if escalated.

Record human quality and the operational decision in post-merge
`evals/phase8d/OUTCOME.md`, added only after the live experiment.

## Run (operator)

Uses production Jung LLM settings (`LLM_BASE_URL`, `MODEL_NAME`, …):

```bash
uv run --locked python -m evals.phase8d.patient_benchmark run-p0-p1 \
  --p2-candidate gemma4-e4b

# Only if the frozen escalation rule reaches P2:
uv run --locked python -m evals.phase8d.patient_benchmark run-p2 \
  --patient-base-url http://127.0.0.1:8081/v1 \
  --patient-model gemma4-e4b
```

P2 flags are **not** hard-coded into generic simulation defaults.

## Post-merge canary

```bash
make simulate-local-llm \
  SIM_ARGS="--scenario social_anxiety --sessions 1 --turns-per-session 2"
```

Add the exact selected patient flags recorded by the P0/P1/P2 decision. P0 adds
none; P1 adds the complete measured `--patient-extra-body-json` replacement object;
P2 adds the selected patient endpoint/model and any measured patient extras.
