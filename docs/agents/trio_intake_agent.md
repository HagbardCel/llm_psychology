# TrioIntakeAgent

## Purpose and Workflow Role
Collects initial user information and therapy goals, establishes a usable
Tier 1 profile, and determines when intake is complete.

## Trigger / Invocation
- Routed by workflow states `NEW` and `INTAKE_IN_PROGRESS`.
- Entry point: `TrioIntakeAgent.process_message`.

References:
- `src/psychoanalyst_app/orchestration/trio_workflow_engine.py`
- `src/psychoanalyst_app/agents/intake/agent.py`

## Inputs
- `message` and `ConversationContext` (session duration, topics covered, history).
- `Settings` for `INTAKE_TOPICS` and `SESSION_DURATION_MINUTES`.
- `LLMService` for Tier 1 extraction.

## Outputs
- `AgentResponse` with prompts or direct content.
- `metadata.user_profile`: `StructuredUserProfileOutput` (Tier 1) when extracted.
- `metadata.intake_complete`: bool used by `AgentResponseHandler` before transitioning.
- `workflow_event`: `START_INTAKE` or `COMPLETE_INTAKE` when appropriate.

## Structured Output Examples

StructuredUserProfileOutput (emitted when Tier 1 extraction succeeds):

```json
{
  "name": "Alex Rivera",
  "alias": "Alex",
  "date_of_birth": "1992-04-17T00:00:00",
  "primary_language": "English",
  "cultural_background": "Latinx",
  "education": "B.A. in Psychology",
  "current_situation": "Managing work stress and sleep issues"
}
```

StructuredTherapyPlanOutput (not emitted by intake; shown for downstream reference):

```json
{
  "selected_therapy_style": "psychoanalysis",
  "plan_details": {
    "focus": "Attachment patterns and anxiety regulation",
    "themes": ["loss", "self-criticism", "avoidance"],
    "techniques": ["free association", "reflective listening"]
  },
  "initial_goals": ["Increase insight into triggers", "Improve sleep routine"],
  "current_progress": "Baseline established",
  "planned_interventions": ["Dream exploration", "Journaling prompts"],
  "status": "active"
}
```

## User Interaction
- Yes, direct dialogue with the user.
- Uses direct response for guest name collection (`metadata.is_direct_response`).

## Side Effects and Persistence
- No direct persistence in the agent.
- `finalize_agent_response` persists `metadata.user_profile` when present.

## Dependencies
- Co-located prompts: `psychoanalyst_app/agents/intake/prompts.py`.
- Slot tracking: `psychoanalyst_app/agents/intake/slots.py`.
- Tier 1 extraction: `psychoanalyst_app/agents/intake/extraction.py`.
- Validator: `build_user_profile_output`.

## Failure Modes and Fallbacks
- On exceptions, returns a generic retry prompt and keeps state unchanged.
- If time is up and intake is incomplete, ends the session without transition.

## Removal Impact
- Users cannot progress from NEW into the workflow.
- Tier 1 profile extraction never occurs, blocking assessment and personalization.

## Observability and Testing Notes
- Key logs include intake completion decisions and topic coverage.
- Intake completion is gated by `metadata.intake_complete`.
