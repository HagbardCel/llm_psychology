# TrioAssessmentAgent

## Purpose and Workflow Role
Analyzes the intake conversation to recommend therapy styles and coordinates
style selection, plus optional plan creation with the selected style.

## Trigger / Invocation
- Routed by workflow states `INTAKE_COMPLETE` and `ASSESSMENT_IN_PROGRESS`.
- Foreground path: `process_message` handles selection flow.
- Background path: `AgentResponseHandler._run_assessment_job` calls
  `process_assessment` after intake completion.

References:
- `src/psychoanalyst_app/agents/assessment/agent.py`
- `src/psychoanalyst_app/orchestration/response_handler.py`
- `src/psychoanalyst_app/orchestration/response_jobs.py`

## Inputs
- `ConversationContext` (message history for intake summary).
- `LLMService` for style assessment.
- `RAGService` and `StyleService` for style prompts and descriptions.
- `TrioDatabaseService` for profile lookups in advanced extraction helpers.
- `TrioReflectionAgent` for plan creation with selected style.

## Outputs
- `AgentResponse` with recommendations and `next_action="await_selection"`.
- `metadata.recommendations`: list of style recommendations used by UI.
- Direct responses for continuation choice and selection clarifications.

## Structured Output Examples

StructuredUserProfileOutput (not emitted by assessment; shown for intake/reflection context):

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

StructuredTherapyPlanOutput (produced when `create_initial_plan_with_style` is used):

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
- Yes, supports style recommendation and selection in-session.
- Also supports a continuation choice prompt (finish vs continue).

## Side Effects and Persistence
- No direct persistence.
- Background job emits `assessment_recommendations` events over WebSocket.

## Dependencies
- Co-located prompts: `psychoanalyst_app/agents/assessment/prompts.py`.
- Recommendation extraction/scoring: `psychoanalyst_app/agents/assessment/recommendations.py`.
- Style selection helpers: `psychoanalyst_app/agents/assessment/selection.py`.
- Initial formulation helpers: `psychoanalyst_app/agents/assessment/initial_formulation.py`.

## Failure Modes and Fallbacks
- If selection cannot be parsed, agent asks for clarification and stays in
  `await_selection`.
- On exception, returns a continue response with error metadata.

## Removal Impact
- No style recommendations; assessment state stalls.
- UI cannot present recommended approaches or proceed to therapy.

## Observability and Testing Notes
- Logs track whether recommendations were previously emitted.
- Recommendations are cached in `AgentResponseHandler` for re-emission.
