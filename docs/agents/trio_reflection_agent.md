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
- `src/psychoanalyst_app/agents/reflection/agent.py`
- `src/psychoanalyst_app/orchestration/response_handler.py`
- `src/psychoanalyst_app/orchestration/persistence.py`

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
  "date_of_birth": "1992-04-17T00:00:00",
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
  "focus": "Attachment patterns and anxiety regulation",
  "themes": ["loss", "self-criticism", "avoidance"],
  "timeline": "12 weeks",
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
- Co-located prompts: `psychoanalyst_app/agents/reflection/prompts.py`.
- Tier pipelines:
  - `psychoanalyst_app/agents/reflection/tier1_pipeline.py`
  - `psychoanalyst_app/agents/reflection/tier2_pipeline.py`
  - `psychoanalyst_app/agents/reflection/tier3_pipeline.py`
  - `psychoanalyst_app/agents/reflection/tier4_pipeline.py`
- Session summary helpers: `psychoanalyst_app/agents/reflection/session_summary.py`.
- Insights pipeline: `psychoanalyst_app/agents/reflection/insights_pipeline.py`.

## Failure Modes and Fallbacks
- Reflection job uses timeout handling and surfaces an error message to the UI.
- On failure, the workflow advances to `PLAN_UPDATE_FAILED`. The ended therapy
  session remains bound for an explicit `retry_plan_update` workflow action.

## Removal Impact
- Therapy plan updates and session briefings are never produced.
- Tiered enrichment and longitudinal analysis are lost.

## Observability and Testing Notes
- Logs capture plan update decisions, briefing generation, and failures.
- Reflection job timeouts use `REFLECTION_TIMEOUT_SECONDS`.
