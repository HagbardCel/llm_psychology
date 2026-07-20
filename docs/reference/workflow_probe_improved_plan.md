---
owner: engineering
status: draft
last_reviewed: 2026-06-13
review_cycle_days: 90
source_of_truth_for: Workflow probe improvement implementation plan
---

# Workflow Probe Improved Plan

## Summary

This plan replaces stale workflow-probe fix actions with a focused sequence for
making probe results trustworthy, explainable, and easier to maintain.

The detailed review remains in
`docs/reference/improved_workflow_probe_plan_review.md`; this file is the concise
implementation checklist. Mark items `[x]` as they are completed.

## Status Checklist

- [x] Confirm `DEFAULT_CONCRETE_STEP_TERMS` already accepts `breath`.
- [x] Confirm intake streaming already uses `phase="intake_response"`.
- [x] Confirm structured-output call sites already use non-null broad phases.
- [x] Define canonical LLM phase constants and replace overloaded phase names.
- [x] Improve LLM timing metrics and user-visible latency undercoverage reporting.
- [x] Share or parity-test backend and probe intake slot evidence logic.
- [x] Skipped: Tighten duration/onset/frequency evidence detection without rejecting coarse onset. User has a different option in mind.
- [x] Align probe risk-screen evidence keywords with backend logic.
- [x] Make console workflow actions WebSocket-first with HTTP polling fallback.
- [x] Add idempotency for one-shot side-effect workflow actions.
- [ ] Add intake conversation-quality metrics and warnings.
- [ ] Add minimal intake prompt constraints after metrics exist.
- [ ] Add separate LLM-user-simulator diagnostic scenarios.
- [ ] Add assessment recommendation evidence spans after probe observability is stable.
- [ ] Add lightweight profile provenance after recommendation evidence is stable.
- [ ] Clarify session briefing semantics.
- [ ] Document `patient_analysis` as Tier 3 dynamic formulation.
- [ ] Keep medical red-flag triage as P3 backlog for this stage.

## Key Changes

### Phase and Timing Taxonomy

Canonical LLM phase constants are defined in
`src/psychoanalyst_app/services/llm_phases.py`, and LLM service entrypoints fail
fast when a phase is missing or unknown. Remap overloaded phases as follows:

- `assessment_generation` becomes separate phases for intake extraction, style
  scoring, and initial Tier 3 formulation.
- `post_session_update` becomes separate phases for session enrichment, session
  summary, memory analysis, plan reflection, Tier 1 profile reflection, Tier 3
  change detection, and Tier 3 update.
- `therapy_response` remains for user-facing therapist responses; deep-topic
  detection gets its own phase.

Keep `timing_no_unphased_llm_calls == 0` strict as a probe artifact check, but
missing phases should now raise before an LLM call reaches the provider. Phase
tests, probe assertions, and scenario thresholds use the canonical phase names
or explicit derived groups.

### Latency Explainability

Build on existing user-visible response timing artifacts. Add provider iterator
boundary timing, prompt-eval or first-token timing, generation duration,
chunk count, completion character count, and `token_count_status`.

Report user-visible timing undercoverage as a warning by default. Only fail a
scenario when that scenario defines an explicit threshold.

### Intake Evidence Parity

Do not add new `slot_evidence` fields; backend and recorder diagnostics already
emit them. Shared logic lives in
`src/psychoanalyst_app/shared/intake_slot_evidence.py` and is consumed by
`agents/intake/slots.py` and the probe recorder. Risk-screen keyword alignment
is satisfied by that shared module, including medical-urgency answer keywords.
Duration-class tightening is intentionally skipped for now; the next approach
will be handled separately.

Skipped for now: replace the broad `since ...` duration regex with explicit
evidence classes:

- precise or rolling duration, such as `for three months` or `past few days`
- frequency, such as `daily` or `twice a week`
- coarse onset, such as `since childhood` or `since I was a kid`
- ambiguous onset, such as `since I was asked to present`, which should not
  complete the duration slot

Align recorder risk-screen answer keywords with backend keywords, including
medical-urgency answers.

### Workflow Action Handling

Make the console client prefer fresh WebSocket `workflow_next_action` events
while keeping HTTP polling as fallback.

Add execution idempotency for one-shot side-effect actions only:

- `complete_profile`
- `select_therapy_style`
- `start_therapy`
- `retry_plan_update`

Do not deduplicate normal chat actions such as `start_intake` and
`continue_therapy`; those represent repeated user turns.

### Conversation Quality Metrics

Add probe metrics before adding hard prompt enforcement:

- intake response average and maximum word count
- intake question count
- repeated opener count
- progress-claim language count
- leading-question pattern count
- topic stagnation count

Then add minimal constraints to the intake prompt: at most one primary question
plus one brief clarifier, concise response length, no unearned progress claims,
and no repeated opener on consecutive turns.

### Later Evidence and Schema Work

Defer larger schema changes until observability is stable:

- Add assessment recommendation evidence spans and preserve them through
  recommendation DTOs, persistence, WebSocket metadata, and formatting.
- Add lightweight profile provenance via evidence JSON or a normalized evidence
  table instead of replacing all profile fields with wrapper models.
- Clarify `session_briefing` semantics by separating session-start briefing
  from post-session handoff.
- Keep and document `patient_analysis` as Tier 3 dynamic formulation.
- Keep medical red-flag triage as P3 backlog for this stage.

## Public Interfaces

Avoid public HTTP or WebSocket DTO changes unless a correlation `call_id` is
intentionally exposed. If contracts change, update:

- `docs/contracts/HTTP_API_CONTRACT.md`
- `docs/WEBSOCKET_PROTOCOL.md`
- generated schemas and protocol constants

Treat probe artifact fields and LLM phase names as observable probe contracts.

## Test Plan

- Extend `tests/unit/test_llm_phase_metadata.py` for canonical phase names.
- Extend workflow probe recorder tests for timing undercoverage, token status,
  duration evidence classes, and risk-screen parity.
- Add console client tests for WebSocket-preferred actions, HTTP fallback, and
  one-shot action idempotency.
- Run targeted tests with `uv run --locked pytest TEST=...`.
- Run `make probe-console-deterministic`.
- Run `make finalization-check` if schemas, contracts, or generated artifacts
  change.

## Assumptions

- `console-ui` remains the only supported frontend.
- Probe reliability and observability take priority over clinical-safety flow
  expansion for this stage.
- Existing completed items are marked `[x]` immediately, and implementation work
  should update this file as items are completed.
