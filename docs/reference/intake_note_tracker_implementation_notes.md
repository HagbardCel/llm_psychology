# Intake Note Tracker Implementation Notes

## What Has Been Done

- Added an internal structured `IntakeRecord` model for incremental intake state.
- Added quoted `IntakeEvidence` with source role, source message index, confidence, and response status.
- Added explicit support for direct-ask unknown/unable answers. These answers are addressed evidence, but not informative clinical evidence.
- Added deterministic intake record merge logic that validates patient quotes and source indexes before accepting patch evidence.
- Added deterministic completeness diagnostics that distinguish missing, addressed, directly asked, and unable-to-answer items.
- Added compact intake-record prompt summaries for response generation.
- Added a note-tracking LLM wrapper that extracts `IntakeRecordPatch` with a dedicated `INTAKE_NOTE_TRACKING` phase.
- Added disabled-by-default feature flags for note tracking, record completion gating, strict quote validation, and direct missing-item asks.
- Added internal persistence for `Session.intake_record` and `intake_record_updated_at`.
- Added SQLite schema support through current DDL, an idempotent additive-column step, and schema version bump.
- Wired `ConversationContext` to load persisted intake records.
- Added an explicit post-agent persistence hook for `intake_record` metadata.
- Integrated the intake agent in diagnostics mode while preserving the existing legacy slot completion gate by default.
- Added deterministic fake and test fixture support for `IntakeRecordPatch`.
- Added focused unit tests for models, merge behavior, completeness, note-tracker phase/prompt wiring, intake-agent metadata/direct-ask guidance, and DB round-trip persistence.
- Verified baseline deterministic workflow behavior with note tracking disabled by default.

## Still Open

- Align `IntakeRecord` with the existing post-completion Tier 1 extraction path.
  - `PatientProfileExtract` currently captures broader background/profile data after legacy intake completion.
  - `IntakeRecord` currently focuses on intake completion evidence and should not replace Tier 1 extraction yet.
  - A later pass should decide whether some Tier 1 fields can be derived from `IntakeRecord`, whether record fields should feed the Tier 1 prompt, or whether both should remain separate.
- Add richer deterministic fake extraction for `IntakeRecordPatch`.
  - Current fake support is intentionally minimal and enough for phase/schema tests.
  - Enabling note tracking in deterministic probes should come with realistic patch outputs for presenting problem, time course, safety, goals, coping, and direct-ask unable answers.
- Add workflow-probe diagnostics for persisted intake records.
  - The record is intentionally internal and not exposed through `SessionDTO`.
  - Probes can read it from DB snapshots or metadata artifacts without changing the HTTP contract.
- Decide when to enable `INTAKE_NOTE_TRACKING_ENABLED` in local or probe settings.
  - It is currently disabled by default to preserve baseline workflow behavior.
  - Enable only after deterministic fake coverage and probe diagnostics are ready.
- Decide when to enable structured direct missing-item prompts.
  - `INTAKE_RECORD_DIRECT_ASK_ENABLED` currently only changes prompt guidance when enabled.
  - Late-intake direct asks should be verified in deterministic and local-LLM probes before becoming default.
- Decide when, if ever, to switch `INTAKE_RECORD_COMPLETION_GATE_ENABLED`.
  - The record gate should remain disabled until diagnostics show parity or intentional improvement over legacy slot evidence.
  - In gate mode, failed note tracking must block completion for that turn unless the previously persisted record was already complete.
- Expand merge and validation tests.
  - Add wrong-source-role and wrong-source-index cases.
  - Add high-confidence replacement over lower-confidence scalar evidence.
  - Add explicit tests for direct-ask unknown/unable patch validation.
- Consider record schema evolution before exposing it externally.
  - The record is stored internally as a JSON dict on `Session`.
  - If clients need it later, update `SessionDTO`, HTTP contract docs, generated schemas, and contract tests in the same change.

## Verification Run

- `make docker-test-one TEST=tests/unit/test_intake_record_models.py`
- `make docker-test-one TEST=tests/unit/test_intake_record_merge.py`
- `make docker-test-one TEST=tests/unit/test_intake_record_completeness.py`
- `make docker-test-one TEST=tests/unit/test_intake_note_tracker.py`
- `make docker-test-one TEST=tests/unit/test_trio_db_service.py`
- `make docker-test-one TEST=tests/unit/test_trio_intake_agent.py`
- `make docker-test-one TEST=tests/unit/test_console_workflow_probe.py`
- `make docker-test-one TEST=tests/unit/test_llm_phase_metadata.py`
- `make probe-console-deterministic`

Ruff passes on the touched implementation and test files. Full `make lint` still reports pre-existing import-order issues in unrelated files.
