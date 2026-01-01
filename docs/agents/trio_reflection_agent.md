# TrioReflectionAgent

## Purpose and Workflow Role
Analyzes completed therapy sessions, updates the therapy plan, generates
session summaries/briefings, and produces Tier 2/3 enrichments.

## Trigger / Invocation
- Routed by workflow state `REFLECTION_IN_PROGRESS`.
- Automatically invoked after session completion via
  `AgentResponseHandler.ensure_reflection_job`.
- Entry points: `process_message` (orchestrator) and `process_reflection`.

References:
- `src/psychoanalyst_app/agents/trio_reflection_agent.py`
- `src/psychoanalyst_app/orchestration/orchestrator_helpers.py`

## Inputs
- `Session` reconstructed from `ConversationContext`.
- `LLMService`, `RAGService`, `TrioDatabaseService`.
- `TrioMemoryAgent` and `TrioPlanningAgent` for analysis and plan updates.
- `Settings` for timeouts and other configuration.

## Outputs
- `AgentResponse` with a reflection summary and `workflow_event` set to
  `COMPLETE_REFLECTION`.
- `metadata.therapy_plan_output`: structured plan update payload.
- `metadata.session_briefing`: briefing used for session resumption.
- `metadata.user_profile`: optional Tier 1 updates.
- `metadata.tier2_enrichment` and `metadata.tier3_update`.

## Structured Output Examples

StructuredUserProfileOutput (emitted when Tier 1 updates are extracted):

```json
{
  "name": "Alex Rivera",
  "alias": "Alex",
  "data_of_birth": "1992-04-17T00:00:00",
  "primary_language": "English",
  "cultural_background": "Latinx",
  "education": "B.A. in Psychology",
  "current_situation": "Managing work stress and sleep issues"
}
```

StructuredTherapyPlanOutput (emitted in `metadata.therapy_plan_output`):

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
- No direct user interaction. Runs as a backend analysis step.

## Side Effects and Persistence
- The agent itself does not persist; the reflection job handler persists:
  - Therapy plan updates
  - Tier 2 enrichment
  - Tier 3 updates
  - Optional Tier 1 profile updates

## Dependencies
- Reflection extractors and helpers:
  - `psychoanalyst_app/agents/reflection/extractors.py`
  - `psychoanalyst_app/agents/reflection/helpers.py`
- Prompt builders: `psychoanalyst_app/prompts/reflection_prompt_builder.py`.

## Failure Modes and Fallbacks
- Reflection job uses timeout handling and surfaces an error message to the UI.
- On failure, the workflow may still advance to `PLAN_COMPLETE`.

## Removal Impact
- Therapy plan updates and session briefings are never produced.
- Tiered enrichment and longitudinal analysis are lost.

## Observability and Testing Notes
- Logs capture plan update decisions, briefing generation, and failures.
- Reflection job timeouts use `REFLECTION_TIMEOUT_SECONDS`.
