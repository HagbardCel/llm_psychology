# TrioIntakeAgent

## Purpose and Workflow Role
Collects initial user information and therapy goals via the canonical structured
`IntakeRecord`, and determines when intake is complete.

Profile enrichment from the intake transcript (family, work history, etc.) now
happens only via post-session reflection (`maybe_update_tier1_profile`), not at
intake completion.

## Trigger / Invocation
- Routed by workflow states `NEW` and `INTAKE_IN_PROGRESS`.
- Entry point: `TrioIntakeAgent.process_message`.

References:
- `src/psychoanalyst_app/orchestration/trio_workflow_engine.py`
- `src/psychoanalyst_app/agents/intake/agent.py`

## Inputs
- `message` and `ConversationContext` (session duration, topics covered, history).
- `Settings` for `INTAKE_TOPICS`, `SESSION_DURATION_MINUTES`, and note-tracking
  tuning (`INTAKE_NOTE_TRACKING_STRICT_QUOTE_VALIDATION`,
  `INTAKE_NOTE_TRACKING_TIMEOUT_SECONDS`).
- `NoteTakerAgent` for structured intake patch extraction (`IntakeRecordPatch`).
- `LLMService` for intake conversational continuation prompts (non-note paths).

## Outputs
- `AgentResponse` with prompts or direct content.
- `metadata.user_profile`: `StructuredUserProfileOutput` only on the guest-name
  bootstrap turn (name collection), not on intake completion.
- `metadata.intake_record`, `metadata.intake_note_tracking`, and
  `metadata.intake_record_completeness` on real intake turns.
- `metadata.topics_covered`: non-gating topic metadata for UI/debugging.
- `metadata.intake_complete`: bool used by `AgentResponseHandler` before transitioning.
- `workflow_event`: `START_INTAKE` or `COMPLETE_INTAKE` when appropriate.

## Flow
1. Guest bootstrap: collect name, no note tracking.
2. Initial prompt: first assistant greeting when history is empty, no note tracking.
3. Real intake turns: `NoteTakerAgent.extract_intake_patch`, merge into `IntakeRecord`, gate uses
   `record_state.gate_complete` (failure-aware via `compute_intake_gate_outcome`).
4. Complete: closing prompt + `COMPLETE_INTAKE` (no intake-time Tier 1 extraction).
5. Incomplete: structured direct-ask continuation for `next_required_item`.

## User Interaction
- Yes, direct dialogue with the user.
- Uses direct response for guest name collection (`metadata.is_direct_response`).

## Side Effects and Persistence
- No direct persistence in the agent.
- `finalize_agent_response` persists `metadata.user_profile` when present (guest name).
- Early intake turn persistence is handled by orchestration (`intake_turn_persistence`).

## Dependencies
- Co-located prompts: `psychoanalyst_app/agents/intake/prompts.py`.
- Topic metadata: `psychoanalyst_app/agents/intake/slots.py` (`identify_covered_topics`).
- Structured record policy: `record_completeness.py`, `runtime.py`.
- Note extraction: `psychoanalyst_app/agents/note_taker/` via injected `NoteTakerAgent`.
- Validator: `build_user_profile_output` (guest name only).

## Failure Modes
- On exceptions, returns a generic retry prompt and keeps state unchanged.
- Note-tracking extraction failures are surfaced in metadata; gate mode may block completion on stale/incomplete records.

## Removal Impact
- Users cannot progress from NEW into the workflow.
- Structured intake records are not maintained, blocking gate-controlled intake completion.

## Observability and Testing Notes
- Key logs include intake completion decisions and topic coverage.
- Intake completion is gated by `metadata.intake_complete` and structured record completeness.
