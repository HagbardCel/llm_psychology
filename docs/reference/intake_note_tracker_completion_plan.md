# Intake Note Tracker Completion Plan

## Executive Summary

The branch `feat/intake-note-tracker` should **not** be opened as a PR in its current form. It contains valuable scaffolding for structured intake note tracking, but it is stale relative to the smaller foundation PRs that have already landed and it still leaves core feature behavior behind flags, partial prompt guidance, and incomplete deterministic/probe coverage.

The goal of this plan is to turn the current branch into a **fully implemented, PR-ready feature** by rebuilding the remaining integration on top of current `main`, using the already-merged `IntakeRecord` domain and SQLite persistence work as the foundation.

The desired end state is:

- Intake note tracking is integrated into the live intake workflow.
- Extracted `IntakeRecordPatch` data is merged into the typed persisted `Session.intake_record`.
- Completion gating and direct asks are coherent and controlled by structured state, not by competing legacy logic.
- Failures are observable and handled differently in diagnostics mode vs. gate mode.
- Deterministic fake extraction and workflow probes validate the feature end-to-end.
- The implementation remains lean, local-runtime oriented, and maintainable.

---

## Current Assessment

### Existing Useful Work

The current branch already contains useful pieces that should be ported or preserved conceptually:

| Area | Current value |
|---|---|
| Note tracker phase | Introduces a dedicated intake note-tracking LLM phase. |
| Patch extraction | Adds extraction of `IntakeRecordPatch` from conversation context. |
| Runtime merge | Adds helpers for preparing intake record state, merging patches, computing completeness, and building prompt context. |
| Prompt support | Adds structured note-tracking instructions with source-message and quote requirements. |
| Metadata | Emits intake record and completeness metadata with assistant responses. |
| Persistence hook | Persists the intake record from response metadata after finalization. |
| Feature flags | Provides flags for note tracking, completion gate, strict quote validation, and direct asks. |
| Unit tests | Adds useful tests around metadata, prompt guidance, DB persistence, and phase wiring. |

### Why It Is Not PR-Ready

The branch is currently best understood as a staging branch, not a finished feature branch.

Primary issues:

1. **It is stale relative to `main`.**
   - `main` already contains the typed `IntakeRecord` domain model.
   - `main` already contains nullable `Session.intake_record` persistence.
   - The branch still carries older/untyped versions of some foundation edits.

2. **The feature is still mostly gated/scaffolded.**
   - Note tracking, direct asks, and structured completion gating are not enabled as one coherent runtime feature.
   - Several TODOs/open items remain explicit in branch docs.

3. **Structured-output failure policy is too permissive.**
   - Note-tracking failures are logged and swallowed.
   - This is acceptable for diagnostics-only mode, but not for completion-gated behavior.

4. **Direct asks are LLM-mediated prompt instructions, not a separate deterministic questioning layer.** This is the accepted design: structured state selects the topic; the intake response LLM phrases the question.

5. **Flag combinations can create invalid runtime states.**
   - Completion gating and direct asks can be enabled without note tracking.

6. **Deterministic fake extraction is incomplete.**
   - Fake extraction currently does not produce realistic `IntakeRecordPatch` data.
   - Workflow probes therefore cannot yet validate the actual feature behavior.

---

## Target Feature Contract

### Functional Contract

When note tracking is enabled during intake:

1. The system extracts a structured `IntakeRecordPatch` from the latest user/assistant turn context.
2. The patch is merged deterministically into the existing typed `IntakeRecord`.
3. The merged record is attached to assistant response metadata.
4. The merged record is persisted to `Session.intake_record` after finalizing the agent response.
5. Intake completeness is computed from the structured record.
6. When the completion gate is enabled, progression out of intake depends on structured completeness.
7. When direct asks are enabled, structured state selects the next missing required item and the intake response LLM asks about it via mandatory prompt instructions (not hardcoded question text).
8. Structured-output failures are visible in metadata and logs.
9. In completion-gate mode, failed extraction must not silently allow workflow progression on stale state.

### Non-Goals

The feature should **not** introduce:

- A new scheduler.
- A new database migration strategy for production compatibility.
- A broad workflow engine rewrite.
- Large new abstractions in `trio_conversation_manager.py`.
- Complex backward-compatibility shims for old local databases.
- Medical/clinical safety policy work beyond keeping the existing data model fields intact.
- Deterministic / hardcoded questioning responses (a separate `build_direct_ask()` return path or canned follow-up text layer).

This is a local laptop application. Favor lean, explicit, reset-friendly implementation over migration-heavy production patterns.

---

## Recommended Branch Strategy

### Preferred Approach

Do **not** continue directly from the old `feat/intake-note-tracker` branch.

Instead:

1. Start from current `main`.
2. Ensure the already-merged foundation work is present:
   - `IntakeRecord`
   - `IntakeRecordPatch`
   - deterministic merge/completeness helpers
   - nullable `Session.intake_record`
   - typed dump/load helpers
3. Re-apply only the remaining runtime integration from `feat/intake-note-tracker`.
4. Keep the resulting PR focused on **live intake note tracking integration**.

### Suggested Branch Name

```bash
git checkout main
git pull
git checkout -b feat/intake-note-tracking-runtime
```

Alternative if you want to preserve the old branch name:

```bash
git checkout feat/intake-note-tracker
git fetch origin
git rebase origin/main
```

However, a clean branch from `main` is preferable because the old branch duplicates already-merged foundation changes.

---

## Implementation Phases

## Phase 0 — Baseline Alignment

### Goal

Establish a clean branch based on current `main` and remove stale duplicate work.

### Tasks

- [ ] Create a fresh branch from current `main`.
- [ ] Verify that the typed intake record model exists.
- [ ] Verify that nullable `Session.intake_record` persistence exists.
- [ ] Verify that typed serialization/deserialization helpers exist.
- [ ] Compare the old branch and port only the remaining runtime integration.
- [ ] Do not reintroduce untyped `dict[str, Any]` session intake records at the domain or conversation boundary.
- [ ] Do not duplicate already-merged tests from foundation PRs unless they need extension.

### Files to inspect

Likely files or current equivalents:

```text
src/psychoanalyst_app/models/intake_record.py
src/psychoanalyst_app/orchestration/models.py
src/psychoanalyst_app/models/domain.py
src/psychoanalyst_app/services/db_serialization.py
src/psychoanalyst_app/services/db/repos/sessions_repo.py
tests/unit/test_intake_record_models.py
tests/unit/test_intake_record_merge.py
tests/unit/test_intake_record_completeness.py
tests/unit/test_trio_db_service.py
```

### Acceptance Criteria

- [ ] Branch diff against `main` contains no duplicated foundation-model work.
- [ ] `Session.intake_record` and `ConversationContext.intake_record` remain typed as `IntakeRecord | None`.
- [ ] Persistence uses typed dump/load helpers, not ad hoc JSON dictionaries.
- [ ] Existing foundation tests still pass.

---

## Phase 1 — Port Runtime Note Tracking Integration

### Goal

Integrate note tracking into the intake runtime using the typed domain model from `main`.

### Tasks

- [ ] Add or port `extract_intake_record_patch`.
- [ ] Add or port note-tracking prompt construction.
- [ ] Add note-tracking phase metadata.
- [ ] Add runtime helper to prepare current intake record state.
- [ ] Merge extracted patch into typed `IntakeRecord`.
- [ ] Compute structured completeness from the typed record.
- [ ] Attach the updated record and diagnostics to assistant response metadata.
- [ ] Persist the updated record after response finalization.

### Design Constraints

- Keep the extractor small and testable.
- Do not let the LLM extractor mutate session state directly.
- Treat extraction as:
  - input: conversation context + current record;
  - output: `IntakeRecordPatch` or structured failure.
- The current record may be provided as context to avoid duplicate extraction, but new evidence in the patch must come only from the latest user message.
- Keep merge/completeness deterministic and outside the LLM path.
- Keep persistence at the finalization boundary, not inside the extractor.

### Suggested Runtime Shape

```python
current_record = context.intake_record or IntakeRecord()
patch_result = await note_tracker.extract_patch(...)

if patch_result.status == "success":
    updated_record = merge_intake_record(current_record, patch_result.patch)
    completeness = evaluate_intake_completeness(updated_record)
elif patch_result.status == "no_new_information":
    updated_record = current_record
    completeness = evaluate_intake_completeness(current_record)
else:
    updated_record = current_record
    completeness = evaluate_intake_completeness(current_record)
    diagnostics.note_tracking_failed = True

metadata["intake_record"] = dump_intake_record(updated_record)
metadata["intake_record_completeness"] = completeness
metadata["intake_note_tracking"] = diagnostics
```

### Acceptance Criteria

- [ ] A successful intake turn can extract, merge, attach, and persist intake record data.
- [ ] The persisted record can be reloaded as a typed `IntakeRecord`.
- [ ] Response metadata includes enough diagnostics for workflow probes.
- [ ] The implementation does not grow orchestration files beyond existing architecture budgets.

---

## Phase 2 — Define Failure Policy

### Goal

Make note-tracking failures explicit and mode-dependent.

### Required Behavior

| Mode | Failure behavior |
|---|---|
| Note tracking disabled | No extraction attempted. No failure. |
| Diagnostics-only note tracking enabled | Log and expose failure metadata; continue response generation. |
| Completion gate enabled | Do not silently proceed on stale state if extraction failed; never emit `COMPLETE_INTAKE` from an incomplete stale record. |
| Existing record already complete | A failed extraction may allow continuation only if the persisted record is already complete and diagnostics clearly show the failure. |

If extraction fails in gate mode and the record is incomplete, route the next turn through structured direct-ask **prompt instructions** for the stale record’s next missing required item and mark metadata with `stale_record_used=true`.

### Tasks

- [ ] Replace bare `None` return on extraction failure with an explicit result object or equivalent status.
- [ ] Add a clear distinction between:
  - `success`
  - `no_new_information`
  - `invalid_patch`
  - `llm_failure`
  - `validation_failure`
  - `timeout`
- [ ] Emit failure status in metadata.
- [ ] In completion-gate mode, block workflow progression if extraction failed and the record is incomplete.
- [ ] If a gate-mode extraction failure leaves an incomplete record, ensure the next turn uses structured direct-ask prompt instructions based on stale state and metadata shows `stale_record_used=true`.
- [ ] Add tests for each relevant failure mode.

### Suggested Result Type

```python
@dataclass(frozen=True)
class IntakePatchExtractionResult:
    status: Literal[
        "success",
        "no_new_information",
        "invalid_patch",
        "llm_failure",
        "validation_failure",
        "timeout",
    ]
    patch: IntakeRecordPatch | None = None
    error_message: str | None = None
    error_code: str | None = None
```

Result invariants:

- `status == "success"` requires `patch is not None`.
- `status != "success"` requires `patch is None`.
- Failure statuses require `error_message` or `error_code`.

### Acceptance Criteria

- [ ] No broad exception-swallowing path can make gate mode silently proceed.
- [ ] Diagnostics-only mode remains resilient.
- [ ] Gate mode is conservative and observable.
- [ ] Unit tests cover success, no-new-info, invalid output, and LLM failure.

---

## Phase 3 — Validate Feature Flag Combinations

### Goal

Prevent invalid runtime configurations.

### Required Invariants

```text
INTAKE_RECORD_COMPLETION_GATE_ENABLED => INTAKE_NOTE_TRACKING_ENABLED
INTAKE_RECORD_DIRECT_ASK_ENABLED     => INTAKE_NOTE_TRACKING_ENABLED
INTAKE_RECORD_COMPLETION_GATE_ENABLED => INTAKE_RECORD_DIRECT_ASK_ENABLED
```

Non-invariant flag behavior:

```text
INTAKE_NOTE_TRACKING_STRICT_QUOTE_VALIDATION has no effect unless
INTAKE_NOTE_TRACKING_ENABLED=true.
```

Strict quote validation should remain `true` by default because it is the desired behavior once note tracking is active. Do not make it a startup invariant, because the default configuration has note tracking disabled and strict quote validation enabled.

For the first fully implemented version, require direct asks in completion-gate mode. This avoids a half-authoritative state where structured completeness blocks workflow progression but the continuation prompt lacks mandatory instructions for the next missing structured item.

### Tasks

- [ ] Add config validation during settings construction/startup.
- [ ] Add unit tests for valid and invalid flag combinations.
- [ ] Fail early with a clear error message for invalid combinations.
- [ ] Document intended flag semantics.

### Recommended Flag Semantics

| Flag | Meaning |
|---|---|
| `INTAKE_NOTE_TRACKING_ENABLED` | Extract and persist structured intake record data. |
| `INTAKE_RECORD_COMPLETION_GATE_ENABLED` | Use structured completeness as the intake progression gate. Requires note tracking. |
| `INTAKE_RECORD_DIRECT_ASK_ENABLED` | Ask targeted questions for missing structured fields. Requires note tracking. |
| `INTAKE_NOTE_TRACKING_STRICT_QUOTE_VALIDATION` | Enforce source quote validation for extracted claims when note tracking is active. No effect while note tracking is disabled. |

### Acceptance Criteria

- [ ] Invalid flag combinations fail fast.
- [ ] Test coverage proves invalid states cannot be accidentally configured.
- [ ] Flag names and semantics are documented in one place.

---

## Phase 4 — Make Structured Direct Asks Authoritative

### Goal

Remove ambiguity between legacy intake follow-up logic and structured direct asks.

### Decision (locked)

**Option A — Structured state owns intake completion and topic selection; the intake response LLM owns phrasing.**

Do **not** add deterministic questioning (hardcoded `build_direct_ask()` responses or a parallel canned-question layer). That adds complexity without improving the core contract: Python already decides *whether* intake can complete and *which* structured item is next; the existing intake response LLM path should ask about that item via mandatory prompt instructions.

### Required behavior

When `INTAKE_RECORD_COMPLETION_GATE_ENABLED=true`:

- Structured completeness decides whether intake can complete.
- Structured state selects `next_required_item` from `IntakeRecordCompleteness`.
- Legacy `required_follow_up` logic is bypassed in gate mode.
- The continuation prompt includes `build_structured_direct_ask_instruction(next_required_item)` so the response LLM must ask about that item.
- Response metadata exposes `intake_next_action_source="structured_direct_ask_llm"` and `selected_direct_ask_item` for observability.
- Legacy diagnostics can remain for comparison when gate is disabled.

### Tasks

- [x] Identify the current point where intake completion/follow-up is decided.
- [x] If structured gate is enabled, compute missing required field from `IntakeRecordCompleteness`.
- [x] Inject structured direct-ask instructions into the intake response prompt (do not return hardcoded question text).
- [x] Ensure legacy required follow-up cannot override structured direct ask in gate mode.
- [x] Keep legacy follow-up available only when structured gate is disabled.
- [x] Add tests for precedence and `selected_direct_ask_item` metadata.

### Example control flow

```python
if settings.INTAKE_RECORD_COMPLETION_GATE_ENABLED:
    completeness = evaluate_intake_completeness(record)

    if not completeness.complete:
        next_missing = completeness.next_required_item
        prompt = build_intake_continuation_prompt(
            ...,
            structured_direct_ask=build_structured_direct_ask_instruction(next_missing),
        )
        # Response LLM generates natural phrasing from prompt + instructions
        intake_next_action_source = "structured_direct_ask_llm"
        selected_direct_ask_item = next_missing
        workflow_action = "continue_intake"
    else:
        workflow_action = "complete_intake"
else:
    workflow_action = legacy_intake_decision(...)
```

### Acceptance criteria

- [x] In gate mode, structured completeness is the single source of truth for completion.
- [x] In gate mode, structured state selects the next missing item; legacy follow-up cannot preempt it.
- [x] Direct asks are LLM-phrased from structured instructions, not deterministic response text.
- [x] Metadata records `selected_direct_ask_item` and `intake_next_action_source`.
- [x] Tests cover both gate-enabled and gate-disabled behavior.

---

## Phase 5 — Complete Prompt and Extraction Contract

### Goal

Make the note-tracking LLM call reliable, constrained, and easy to validate.

### Prompt Requirements

The extraction prompt should require:

- Only extract facts supported by the conversation.
- For the initial implementation, only produce evidence from the latest user message.
- Do not cite arbitrary prior messages unless merge validation is extended to validate quotes against the full message history.
- Include the latest user message source index on extracted evidence.
- Include short quotes for claim support when strict validation is enabled.
- Do not infer or embellish.
- Leave absent fields empty.
- Use `unknown` / `unable_to_answer` only when the patient explicitly gives that answer, with quote/source evidence and `direct_ask=True`.
- Return a valid `IntakeRecordPatch`.
- Support `no_new_information` when no useful update exists.

### Tasks

- [x] Align prompt fields exactly with `IntakeRecordPatch`.
- [x] Remove any stale fields from older branch versions.
- [x] Add a prompt/schema contract test that compares prompt-declared field names with the actual `IntakeRecordPatch` schema.
- [x] Add examples for:
  - presenting problem (`presenting_problem.main_concern`)
  - time course (`presenting_problem.time_course.duration_or_onset`)
  - goals (`goals.therapy_goals`)
  - coping attempts (`coping.attempted_strategies`)
  - functional impairment / avoidance (`presenting_problem.functional_impairment`)
  - relevant clinical context via existing schema paths such as `presenting_problem.main_concern`, `presenting_problem.symptoms`, or `presenting_problem.functional_impairment`
  - unable/unknown answers
  - no-new-information turns
- [x] Ensure source-message and quote fields match validation expectations.
- [x] Add tests for prompt construction.

### Acceptance Criteria

- [x] Prompt schema and domain schema cannot drift silently, even though intake record models ignore extra fields at runtime.
- [x] The extractor can produce meaningful patches for common intake utterances.
- [x] The extractor leaves unmentioned fields empty and represents explicitly stated “unknown” / “unable” answers cleanly.
- [x] Strict quote validation can be tested deterministically.

---

## Phase 6 — Deterministic Fake Extraction

### Goal

Make local workflow probes validate the actual feature without relying on a real LLM.

### Problem

The current fake extraction path only returns minimal “no new information” output. That prevents probes from testing realistic intake record progression.

### Tasks

- [ ] Extend the deterministic fake LLM or fake structured-output path to emit realistic `IntakeRecordPatch` values.
- [ ] Cover at least the core required fields.
- [ ] Make outputs deterministic from known probe transcripts.
- [ ] Include cases for:
  - first meaningful user disclosure
  - additional detail in later turns
  - risk/safety screen answer
  - direct answer to a missing-field question
  - unable/unknown answer
  - no new information
  - malformed/failed structured output if failure policy is tested
- [ ] Add unit tests for fake extraction behavior.

### Example Fake Extraction Cases

| User text pattern | Expected patch behavior |
|---|---|
| “I struggle with procrastination and anxiety” | Update presenting problem. |
| “This has been going on for years” | Update time course. |
| “I want more confidence and agency” | Update goals. |
| “I avoid letters and admin tasks” | Update `presenting_problem.functional_impairment` (avoidance pattern). |
| “I usually distract myself” | Update coping attempts. |
| “I have no thoughts of harming myself or anyone else, and nothing medically urgent.” | Populate `safety.self_harm`, `safety.harm_to_others`, and `safety.medical_urgency`. |
| “I don’t want to answer that.” after a risk ask | Mark the relevant safety field as `unable_to_answer` with `direct_ask=True`. |
| “I don’t know” | Mark asked item as unknown/unable, not missing forever. |
| Generic small talk | Return no-new-information. |

### Acceptance Criteria

- [x] Fake extraction produces realistic records in deterministic probes.
- [x] Probe can verify structured intake progression without a real model.
- [x] Tests cover fake extraction for all required fields.

---

## Phase 7 — Workflow Probe Diagnostics

### Goal

Make the workflow probe assert that the feature works end-to-end.

### Required Probe Observability

The probe should be able to inspect:

- whether note tracking was enabled;
- whether extraction was attempted;
- extraction status per intake turn;
- merged intake record after each relevant turn;
- completeness status after each relevant turn;
- selected missing field (`selected_direct_ask_item` metadata);
- persisted final `Session.intake_record`;
- whether intake completion was gated by structured completeness.

### Tasks

- [x] Add structured metadata to assistant responses.
- [x] Persist record after finalization.
- [x] Add DB snapshot or diagnostics field for final intake record.
- [x] Add workflow-probe assertions for final persisted record existence.
- [x] Add workflow-probe assertions for required fields (populated or explicitly marked unknown/unable).
- [x] Add workflow-probe assertion for final structured completion (canonical completion decision).
- [x] Add final workflow-state assertion.
- [ ] Add per-turn completeness-transition assertions (deferred; see note below).
- [ ] Add per-turn `selected_direct_ask_item` assertions (deferred; see note below).
- [ ] Add no-duplicate/conflicting-workflow-action assertion (not in this phase).
- [x] Add a concise probe summary section for intake note tracking.

> Phase 7 implementation note: per-turn assertions (`selected_direct_ask_item`
> per turn, per-turn completeness transitions) were intentionally deferred —
> per-turn intake metadata is not currently sent over WebSocket or persisted
> per-message. The probe asserts from the final persisted
> `sessions.intake_record` snapshot using the backend's canonical
> `intake_record_completion_decision`, plus per-item user-sourced evidence
> integrity. See `console-ui/scenarios/workflow-probes/intake_note_tracking.json`
> and `make probe-console-intake-notes`.

### Implemented Probe Assertions

These ship in this phase via `console-ui/src/workflow_probe/assertions.py` and assert against the final persisted `sessions.intake_record`:

```text
assert intake_record_persisted
assert intake_record_parseable_as_intake_record
assert intake_record_has_presenting_problem
assert intake_record_has_duration
assert intake_record_has_risk_screen
assert intake_record_has_functional_impairment
assert intake_record_has_goal_or_unknown
assert intake_record_has_goal            # informative goal (scenario-gated)
assert intake_record_has_coping
assert intake_record_has_sleep_impact
assert intake_record_completion_decision_complete
assert intake_record_completion_source_is_canonical
assert workflow_advanced_past_intake_in_progress
assert structured_intake_completion_supported_by_persisted_record
assert intake_record_items_have_user_sourced_evidence
assert intake_evidence_survived_merge
```

### Future Probe Assertions

These require per-turn intake metadata, which is not currently sent over WebSocket or persisted per-message; see the deferred task bullets above.

```text
assert selected_direct_ask_item_matches_missing_field
assert structured_gate_prevented_premature_completion
assert final_response_metadata_intake_record_matches_reloaded_session_intake_record
```

### Acceptance Criteria

- [x] Probe failure clearly identifies whether the problem is extraction, merge, persistence, direct-ask selection, or gating.
- [x] Probe output contains enough evidence to debug without manually reading the database.
- [x] The final persisted record matches the expected deterministic transcript.

---

## Phase 8 — Test Plan

### Unit Tests

Add or update unit tests for:

#### Domain / Merge

- [ ] Empty record initialization.
- [ ] Patch merge into empty record.
- [ ] Patch merge preserving existing data.
- [ ] Patch merge replacing only allowed fields.
- [ ] Unknown/unable values.
- [ ] Completeness calculation.
- [ ] Completeness after partial updates.
- [ ] Completeness after all required data present.

#### Extractor

- [ ] Successful structured patch extraction.
- [ ] No-new-information response.
- [ ] Invalid structured output.
- [ ] LLM exception.
- [ ] Timeout.
- [ ] Strict quote validation success.
- [ ] Strict quote validation failure.

#### Runtime Integration

- [ ] Note tracking disabled: no extraction call.
- [ ] Note tracking enabled: extraction call occurs.
- [ ] Successful extraction updates metadata.
- [ ] Successful extraction persists record.
- [ ] Diagnostics-only extraction failure continues.
- [ ] Gate-mode extraction failure does not silently progress.
- [ ] Existing complete record can progress despite extraction failure, with diagnostics.
- [ ] Structured gate overrides legacy follow-up.
- [ ] Legacy behavior remains when structured gate disabled.

#### Config

- [ ] Valid default flags.
- [ ] Note tracking enabled alone is valid.
- [ ] Completion gate without note tracking is invalid.
- [ ] Direct ask without note tracking is invalid.
- [ ] Strict quote validation without note tracking is valid and has no effect.

#### Fake Model

- [ ] Fake extraction emits presenting problem.
- [ ] Fake extraction emits goals.
- [ ] Fake extraction emits time course.
- [ ] Fake extraction emits coping/current blockers.
- [ ] Fake extraction handles unknown/unable.
- [ ] Fake extraction handles no-new-information.

### Integration Tests

- [ ] Session can complete intake with structured note tracking.
- [ ] Session cannot complete intake prematurely in gate mode.
- [ ] Persisted record survives repository round trip.
- [ ] Assistant response metadata and stored session state agree.
- [ ] `selected_direct_ask_item` metadata changes as missing fields are resolved.

### Workflow Probe

- [x] Deterministic probe with fake extraction passes.
- [ ] Optional local-LLM probe validates real extraction path.
- [x] Probe summary includes intake record diagnostics.
- [x] Probe DB snapshot includes final typed intake record.

---

## Phase 9 — Validation Commands

All commands should run through the Docker-backed Make targets from `AGENTS.md`; do not run Python or pytest directly on the host.

During development, run targeted checks plus architecture validation:

```bash
make docker-test-one TEST=tests/unit/test_intake_record_models.py
make docker-test-one TEST=tests/unit/test_intake_record_merge.py
make docker-test-one TEST=tests/unit/test_intake_record_completeness.py
make docker-test-one TEST=tests/unit/test_trio_db_service.py
make docker-test-one TEST=tests/unit/test_trio_intake_agent.py
make validate-architecture
```

Before opening the PR, run the release-candidate check:

```bash
make finalization-check
```

If debugging a specific probe issue, these checks are useful:

```bash
make probe-console-deterministic
make probe-console-local-llm
```

Important: avoid adding more weight to large orchestration files, especially if they are already close to the line-count budget. Prefer small helper modules over expanding `trio_conversation_manager.py`.

---

## Phase 10 — PR Readiness Checklist

Do not open the PR until all of the following are true.

### Branch Hygiene

- [ ] Branch is based on current `main`.
- [ ] No stale duplicate model/persistence code from the old branch.
- [ ] Diff is focused on runtime note-tracking integration.
- [ ] No unrelated cleanup mixed in.
- [ ] No broad production migration logic added.

### Runtime Behavior

- [ ] Note tracking extracts structured patches during intake.
- [ ] Patches merge into typed `IntakeRecord`.
- [ ] Updated record is attached to response metadata.
- [ ] Updated record is persisted after finalization.
- [ ] Completion gate uses structured completeness when enabled.
- [ ] Structured state selects the next missing item in gate mode; the response LLM phrases the question via prompt instructions.
- [ ] Legacy follow-up logic does not override structured direct asks in gate mode.
- [ ] Failure policy is explicit and tested.

### Configuration

- [x] Invalid flag combinations fail fast.
- [x] Default local behavior is documented.
- [x] Feature can be enabled for deterministic workflow probe.
- [ ] Feature can be run with local LLM backend.

### Tests and Probes

- [x] Unit tests pass.
- [ ] Integration tests pass.
- [x] Architecture validation passes.
- [x] Deterministic workflow probe passes.
- [ ] Local-LLM probe either passes or has a clearly documented non-blocking reason.
- [x] Probe output confirms persisted intake record.

### Documentation

- [ ] Short feature description added.
- [ ] Flag semantics documented.
- [ ] Probe diagnostics documented.
- [ ] PR description includes test commands and results.

---

## Suggested PR Description

```markdown
## Summary

Implements runtime intake note tracking on top of the existing typed `IntakeRecord` domain and SQLite persistence foundation.

The feature extracts structured `IntakeRecordPatch` updates during intake, merges them deterministically into the persisted session intake record, computes structured completeness, and uses that state to select the next missing item for LLM-mediated direct asks and, when enabled, completion gating.

## Key Changes

- Add intake note-tracking runtime extraction.
- Merge extracted patches into typed `IntakeRecord`.
- Persist updated intake record after response finalization.
- Add explicit extraction diagnostics and failure policy.
- Add config validation for note-tracking flag combinations.
- Make structured gate authoritative; direct asks via LLM prompt instructions (no deterministic questioning layer).
- Extend deterministic fake extraction for workflow probes.
- Add unit/integration/probe coverage.

## Validation

- [ ] `make finalization-check`
- [ ] `make probe-console-local-llm`, if applicable

## Notes

This PR intentionally avoids production migration complexity. The app is local-first and can reset/recreate local databases during development.
```

---

## Risk Register

| Risk | Impact | Mitigation |
|---|---:|---|
| Stale branch reintroduces old model/persistence code | High | Rebuild from current `main`; port only runtime integration. |
| LLM extraction silently fails | High | Explicit result object and gate-mode failure policy. |
| Direct ask conflicts with legacy follow-up | High | Gate mode bypasses legacy follow-up; LLM instructions carry topic selection |
| Invalid flag combinations | Medium | Startup config validation. |
| Fake extraction too weak | Medium | Add deterministic patches for core intake fields. |
| Orchestration file exceeds architecture budget | Medium | Extract helpers into small modules. |
| Prompt/schema drift | Medium | Tests tying prompt field names to `IntakeRecordPatch`. |
| Probe diagnostics insufficient | Medium | Add explicit metadata and DB snapshot assertions. |

---

## Recommended Implementation Order

1. **Fresh branch from `main`.**
2. **Port runtime extraction and merge helpers.**
3. **Use typed persistence helpers only.**
4. **Add explicit extraction result/failure policy.**
5. **Add config validation.**
6. **Make structured gate authoritative with LLM-mediated direct asks.**
7. **Extend fake extraction.**
8. **Add unit/integration tests.**
9. **Add workflow-probe diagnostics and assertions.**
10. **Run finalization checks.**
11. **Open PR only after the deterministic probe proves end-to-end behavior.**

---

## Final Definition of Done

The feature is fully implemented when a deterministic intake workflow can demonstrate the following without relying on manual inspection:

1. User provides intake-relevant information.
2. Note tracker extracts a structured patch.
3. Patch is merged into a typed intake record.
4. Record completeness changes over the session.
5. Metadata shows the assistant turn targeted the next missing structured item (`selected_direct_ask_item`), phrased by the response LLM.
6. Intake does not complete prematurely in gate mode.
7. Completed or explicitly unknown fields allow intake completion.
8. Final persisted session contains the expected `IntakeRecord`.
9. Probe output shows extraction, merge, completeness, selected direct-ask item, and persistence diagnostics.
10. `make finalization-check` passes.
