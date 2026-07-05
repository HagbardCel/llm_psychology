# NoteTakerAgent

## Purpose and Workflow Role

Stateless supporting agent for LLM-backed clinical note operations:

- structured intake `IntakeRecordPatch` extraction during intake turns
- session summary payload generation after therapy sessions
- session briefing generation for the next session

`NoteTakerAgent` is not workflow-routed. Intake and reflection agents call it as an injected dependency.

## Trigger / Invocation

- Created by `ServiceContainer` as `note_taker_agent` (singleton supporting service).
- Injected into `TrioIntakeAgent` and `TrioReflectionAgent`.
- Intake runtime calls `note_taker_agent.extract_intake_patch` via the `IntakePatchExtractor` protocol.

References:

- `src/psychoanalyst_app/agents/note_taker/agent.py`
- `src/psychoanalyst_app/container/service_container.py`

## Inputs

- `intake_llm_service`: routed INTAKE model for patch extraction (`INTAKE_NOTE_TRACKING` phase).
- `reflection_llm_service`: routed REFLECTION model for summaries/briefings (`SESSION_SUMMARY`, `SESSION_ENRICHMENT` phases).
- `Settings` for briefing prompt configuration.
- Per-call inputs: `IntakeRecord`, latest `Message` pair, `Session`, reflection context dicts.

## Outputs

- `IntakePatchExtractionResult` for intake patch extraction.
- Session summary payload dict (`session_id`, `summary`, `timestamp`).
- Session briefing dict (validated `SessionBriefing` JSON) or `None` on validation failure.

## Package Layout

```text
agents/note_taker/
  agent.py           # NoteTakerAgent facade
  intake_patch.py    # IntakeRecordPatch extraction
  intake_contract.py # Prompt contract for intake note tracking
  session_notes.py   # Session summary and briefing generation
```

## Dependencies

- Intake merge/completeness/gating remain in `agents/intake/runtime.py`.
- Reflection coordination (plan update, tier pipelines) remains in `TrioReflectionAgent`.
- Probe fake extraction hooks the LLM layer (`testing/intake_fake_extraction.py`), not `NoteTakerAgent`.

## Failure Modes

- Intake extraction failures return structured `IntakePatchExtractionResult` statuses; runtime decides gate behavior.
- Briefing validation failures raise after deterministic evidence checks in `session_notes.py`.

## Observability and Testing Notes

- LLM phases: `intake_note_tracking`, `session_summary`, `session_enrichment`.
- Unit tests: `tests/unit/test_note_taker_intake_patch.py`, reflection pipeline briefing tests.
