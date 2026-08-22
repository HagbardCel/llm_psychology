# Phase 8D — synthetic patient cost benchmark outcome

## Environment / provenance

- **Run date:** 2026-08-22
- **Therapist/session endpoint:** `http://127.0.0.1:8000/v1`
- **Therapist/session model:** `mtplx-qwen38-27b-optimized-speed` (Qwen 3.8 27B)
- **Patient candidate endpoint:** `http://127.0.0.1:1234/v1`
- **Patient candidate model:** `google/gemma-4-e4b` (Gemma4-E4B)
- **Scenario:** `social_anxiety`, contexts A–D
- **Raw artifacts:**
  - `logs/phase8d/run-20260822T125518Z/benchmark.json` (P0/P1)
  - `logs/phase8d/run-20260822T134726Z/benchmark.json` (P2)
  - `logs/simulations/run-20260822T134743Z-83c56695/` (canary, default Qwen extras)
  - `logs/simulations/run-20260822T135330Z-13c10541/` (canary, thinking disabled)

The log and simulation artifacts are gitignored operator evidence. They are
retained locally and are cited by run ID here.

## Benchmark results

| Arm | Calls | Total latency | Failures | Quality review |
| --- | ---: | ---: | ---: | --- |
| P0 — Qwen patient, implicit endpoint | 4 | 49.043 s | 0 | PASS A/B/C/D |
| P1 — Qwen patient, thinking disabled | 4 | 8.664 s | 0 | PASS A/B/C/D |
| P2 — Gemma4-E4B patient, port 1234 | 4 | 21.845 s | 0 | PASS A/B/C/D |

All reviewed outputs were first-person patient speech, consistent with the
supplied context, and free of visible meta/reasoning leakage. P2 was 44.5% of
P0 total latency and therefore met the documented P2 threshold (≤85% of P0).

Under the frozen protocol, P1 already met its quality and ≤90%-of-P0 rule,
so P1 is the protocol-selected arm and P2 would ordinarily not be run. P2 was
run because the operator explicitly requested Gemma4-E4B for the patient.

## Whole-product canary

The required one-session/two-turn `social_anxiety` canary was attempted with
Qwen as therapist and Gemma4-E4B as patient.

Both attempts reached the real HTTP product and completed patient calls, but
failed before READY during the therapist `intake_patch` structured-output
request. Jung performed the permitted single correction attempt and then
returned `chat_invalid_llm_output`:

1. `run-20260822T134743Z-83c56695`: failed with no therapist extra body.
2. `run-20260822T135330Z-13c10541`: failed again with
   `JUNG_LLM_EXTRA_BODY_JSON='{"chat_template_kwargs":{"enable_thinking":false}}'`.

The first artifact records three successful Gemma patient calls with complete
usage coverage; the failure is on the Qwen structured-output path, not patient
endpoint reachability. The second attempt confirms that disabling Qwen
thinking did not make this model/server combination satisfy Jung's
`IntakeRecordPatch` schema.

### Exact violations — thinking-enabled run

The first canary (`run-20260822T134743Z-83c56695`) has complete diagnostic
capture in `runtime/trace.jsonl`. The relevant correlation is:

- session model: `mtplx-qwen38-27b-optimized-speed`
- task: `intake_patch`
- response format: strict JSON Schema `IntakeRecordPatch`
- initial attempt: `provider-1`, trace sequences 10–12
- correction attempt: `provider-2`, trace sequences 14–16 (accepted)
- terminal attempt: `provider-7`, trace sequences 46–49

The structural rule violated was:
`response_status in {unknown, unable_to_answer} requires direct_ask=true`.

Initial `provider-1` validation (trace sequence 12) reported these exact
paths:

```text
presenting_problem.main_concern
presenting_problem.symptoms[0]
presenting_problem.time_course.duration_or_onset
presenting_problem.time_course.frequency
presenting_problem.time_course.trajectory
```

Each path had `response_status="unknown"` with `direct_ask=false`. The initial
response also used that same invalid combination at
`presenting_problem.functional_impairment` and
`presenting_problem.sleep_impact`; those two fields were not included in the
validator's reported reason because the processor stopped at the surfaced
semantic errors. The provider returned valid JSON syntax, but it was
semantically invalid for Jung's Pydantic model.

The correction request included the validation reason and the invalid JSON.
`provider-2` repaired that first violation set and was accepted (trace
sequence 16). The run then continued through additional intake exchanges.
The terminal failure occurred later, on `provider-7`, after `provider-6`'s
initial response reported a new violation set. This is the specific reason
the run terminated; it was not a transport timeout, malformed JSON parse,
missing required top-level key, or provider connection failure.

For completeness, the same thinking-enabled trace shows another intake patch
cycle at `provider-4` and the terminal cycle at `provider-6` /
`provider-7`. The latter's exact surfaced violations were:

```text
presenting_problem.time_course.frequency
presenting_problem.sleep_impact
```

Again, both were `response_status="unknown"` with `direct_ask=false` in the
`provider-7` correction response; `provider-7` repeated the violations after
the correction prompt. These records explain why the whole-product run could
progress through several intake exchanges before the terminal failure, and
provide provider-attempt IDs and trace sequence numbers for direct forensic
lookup without reproducing full prompts or transcripts.

## Decision and status

- **Measured performance candidate:** Gemma4-E4B (P2) is materially faster
  than the implicit Qwen patient arm and passed the context-level quality
  review.
- **Frozen-protocol selection:** P1, because it was the first passing arm
  under the stop rule.
- **Operator-requested configuration:** Qwen 3.8 27B therapist on port 8000
  plus Gemma4-E4B patient on port 1234.
- **Phase status:** **INCOMPLETE — whole-product canary failed**.

The performance benchmark itself is complete. Phase 8D must not be marked
passed until the therapist structured-output incompatibility is resolved or a
compatible Qwen serving/request configuration is supplied and the canary
passes its mechanical audit.
