# TrioPlanningAgent

## Purpose and Workflow Role
Creates and updates therapy plans based on intake/therapy sessions,
therapy style preferences, and memory insights. Tracks plan evolution.

## Trigger / Invocation
- Invoked by `TrioReflectionAgent` for plan updates.
- Invoked by `TrioAssessmentAgent` (via reflection) for initial plans.
- Entry points: `create_initial_plan`, `update_plan`, and
  `build_structured_plan_output`.

References:
- `src/psychoanalyst_app/agents/trio_planning_agent.py`

## Inputs
- `Session` and current `TherapyPlan` where applicable.
- `LLMService`, `RAGService`, `StyleService`.
- `TrioMemoryAgent` for session context and longitudinal memory.

## Outputs
- `StructuredTherapyPlanOutput` payloads (no persistence).
- Plan evolution metadata held in-memory (`PlanEvolution`, `PlanningStrategy`).

## Structured Output Examples

StructuredUserProfileOutput (not emitted by planning; shown for reference):

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

StructuredTherapyPlanOutput (emitted by this agent):

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
- No direct user interaction.

## Side Effects and Persistence
- Does not write to the database.
- Reflection job persists output via `persist_therapy_plan_from_output`.

## Dependencies
- Planning analysis: `psychoanalyst_app/agents/planning/analysis.py`.
- Planning extractors: `psychoanalyst_app/agents/planning/extractors.py`.
- Formatting helpers: `psychoanalyst_app/agents/planning/formatting.py`.

## Failure Modes and Fallbacks
- Raises `PlanningError` for unrecoverable plan creation failures.
- `create_initial_plan` is shielded from cancellation for data integrity.

## Removal Impact
- No therapy plan generation or evolution.
- Assessment and reflection phases lose critical outputs.

## Observability and Testing Notes
- Logs capture plan generation steps and memory usage.
- Health checks validate downstream dependencies.
