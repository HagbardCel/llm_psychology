# Phase 8D — synthetic patient cost benchmark outcome

**Status: CLOSED WITH KNOWN PRODUCT FOLLOW-UP**

Known product follow-up: [#72](https://github.com/HagbardCel/llm_psychology/issues/72)
(Harden intake `direct_ask` bookkeeping ownership).

## Selection

**Selected arm: P1**

Reason:

- quality PASS A/B/C/D
- 8.664 s vs P0 49.043 s
- satisfies frozen ≤90% stop rule

P2/Gemma4-E4B was an operator-requested post-selection diagnostic. It does
**not** alter the frozen P1 decision.

## Exact operational configuration

```text
Patient endpoint: implicit session endpoint
Patient model: implicit session model
Patient extra_body:
{"chat_template_kwargs":{"enable_thinking":false}}
```

Derived from P0/P1 benchmark `logs/phase8d/run-20260822T125518Z/benchmark.json`
where `session.extra_body` was `null`, so P1's complete replacement object is
exactly the thinking-disabled body above.

## Benchmark results

| Arm | Calls | Total latency | Failures | Quality review |
| --- | ---: | ---: | ---: | --- |
| P0 — Qwen patient, implicit endpoint | 4 | 49.043 s | 0 | PASS A/B/C/D |
| P1 — Qwen patient, thinking disabled | 4 | 8.664 s | 0 | PASS A/B/C/D |
| P2 — Gemma4-E4B patient, port 1234 | 4 | 21.845 s | 0 | PASS A/B/C/D |

Raw artifacts (gitignored, cited by run ID):

- `logs/phase8d/run-20260822T125518Z/benchmark.json` (P0/P1)
- `logs/phase8d/run-20260822T134726Z/benchmark.json` (P2)

## Selected-arm P1 canary (counted)

| Field | Value |
| --- | --- |
| Run ID | `run-20260826T082215Z-e24dc2e4` |
| git_commit | `3faab42cf4214d5b357c69743f0f17c51b10821c` (Phase 8 merge SHA) |
| git_worktree_dirty | `false` |
| Status | failed |
| Terminal error | `chat_invalid_llm_output` on therapist `intake_patch` |
| Task | `intake_patch` (initial + one correction) |
| Mechanical ownership | unchanged product therapist path |

`patient_metrics` (exact P1 provenance observed):

```json
{
  "calls": 1,
  "patient_model": "mtplx-qwen38-27b-optimized-speed",
  "patient_endpoint": "http://127.0.0.1:8000/v1",
  "patient_extra_body": {
    "chat_template_kwargs": {
      "enable_thinking": false
    }
  },
  "usage_coverage": 1.0,
  "latency_seconds_total": 2.2616131249815226
}
```

Validation reason (correction attempt, trace sequence 16):

```text
unknown/unable intake evidence requires direct_ask=True
```

on `presenting_problem.main_concern`, `symptoms[0]`, `symptoms[1]`,
`time_course.duration_or_onset`, and `time_course.frequency`. Provider returned
valid JSON with `response_status` in `{unknown, unable_to_answer}` and
`direct_ask=false`.

### Classification

```text
patient optimization: validated (P1 benchmark + canary patient path)
patient endpoint/config integration: reached successfully
therapist intake_patch: failed on pre-existing semantic reliability defect
Phase 8 causality: no evidence Phase 8 caused the failure
```

Phase 8C already observed the same `direct_ask` semantic failures on MTPLX/Qwen
before this lean-closure branch. The lean-closure PR has no `src/jung/**` diff.

### External invalidation (does not count)

`run-20260826T080549Z-a3f35b82` failed immediately with `LLMProtocolError`
because MTPLX lacked `llguidance` for `json_schema`. Documented fixture fix
(`llguidance==1.8.0` installed; server restarted). One replacement canary was
then run (the counted run above). No third attempt.

## P2 diagnostic history (retained; not selection)

Operator-requested Qwen therapist + Gemma4-E4B patient canaries:

1. `run-20260822T134743Z-83c56695` — `chat_invalid_llm_output` (`direct_ask`)
2. `run-20260822T135330Z-13c10541` — same with therapist thinking disabled

These confirm patient endpoint reachability and the therapist
`intake_patch` structured-output **reliability** issue (not a deterministic
incompatibility). They do not change P1 selection.

## Therapist / fixture provenance (verified at canary time)

| Item | Value |
| --- | --- |
| Therapist/session endpoint | `http://127.0.0.1:8000/v1` |
| Therapist/session model | `mtplx-qwen38-27b-optimized-speed` |
| Model artifact | `Youssofal/Qwen3.8-27B-MTPLX-Optimized-Speed` |
| MTPLX version | **2.9.2** (observed) |
| llguidance | **1.8.0** (installed for fixture; required for `json_schema`) |
| Launch options (observed) | `--scheduler-mode serial --ssd-session-cache off --reasoning-effort low --no-auth --model-id mtplx-qwen38-27b-optimized-speed` |
| Server reasoning_effort | `low` (verified via launch argv) |
| Effective therapist request extra_body | `null` (no `JUNG_LLM_EXTRA_BODY_JSON`) |
| Effective intake_patch task override | none (`JUNG_LLM_TASK_CONFIG_JSON` unset) |
| Structured mode | `intake_patch=json_schema` (product default) |
| Intake prompt | intake-v2 (unchanged product path) |

## Phase 8 closure

| Area | Closure state |
| --- | --- |
| 8A eval-report concurrency | Retained |
| 8B backend/server benchmarking | Historical experiment closed; reusable workflow retained |
| 8C multi-journey concurrency | Rejected/removed |
| 8D patient cost | **P1 selected**; exact operational override recorded |
| Whole-product evidence | Exactly one provenance-valid **P1** 1×2 canary attempted |
| Qwen `direct_ask` issue | Classified; tracked in #72 outside Phase 8 |
| Future Phase 8 work | **None** |
