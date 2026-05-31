# TrioTherapistAgent

## Purpose and Workflow Role
Conducts the primary therapy conversation, using the current therapy plan
and session context to generate prompts and drive workflow transitions.

## Trigger / Invocation
- Routed by workflow states `ASSESSMENT_COMPLETE`, `THERAPY_IN_PROGRESS`,
  and `PLAN_UPDATE_COMPLETE`.
- Entry point: `process_message`.

References:
- `src/psychoanalyst_app/agents/therapist/agent.py`
- `src/psychoanalyst_app/orchestration/trio_workflow_engine.py`

## Inputs
- `ConversationContext` including `therapy_plan` and session history.
- `LLMService` for prompt responses.
- `RAGService` for contextual knowledge retrieval.
- `StyleService` for style configuration and prompt building.
- `Settings` for session time and briefing validity windows.

## Outputs
- `AgentResponse` with LLM prompt content.
- `workflow_event` transitions:
  - `START_THERAPY` when entering therapy for the first time.
  - `COMPLETE_SESSION` when time expires.
- `metadata` includes therapy style and time management flags.

## Structured Output Examples

StructuredUserProfileOutput (not emitted by this agent; shown for reference):

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

StructuredTherapyPlanOutput (not emitted by this agent; shown for reference):

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
- Yes, this is the primary interactive therapy agent.
- Prompts are streamed through the LLM unless `is_direct_response` is set.

## Side Effects and Persistence
- No direct persistence.
- Session completion triggers reflection via the orchestrator.

## Dependencies
- Co-located prompts: `psychoanalyst_app/agents/therapist/prompts.py`.
- Session policy: `psychoanalyst_app/agents/therapist/session_policy.py`.
- Deep-topic detection: `psychoanalyst_app/agents/therapist/deep_topic.py`.
- Briefing evaluation with `BriefingStatus`.

## Failure Modes and Fallbacks
- If no therapy plan is available, returns an error prompt and continues.
- On exceptions, returns a generic retry response.

## Removal Impact
- Core therapy conversations cannot proceed.
- Workflow loop (therapy -> reflection -> plan -> therapy) is broken.

## Observability and Testing Notes
- Logs include workflow transitions and session time management.
- Briefing freshness is evaluated via `get_briefing_status`.
