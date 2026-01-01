# TrioMemoryAgent

## Purpose and Workflow Role
Maintains and analyzes longitudinal session memory, extracting themes,
patterns, and continuity context for planning and reflection.

## Trigger / Invocation
- Invoked by `TrioPlanningAgent` and `TrioReflectionAgent`.
- Entry points: `analyze_session_context`, `get_therapeutic_memory`,
  `identify_patterns`, `get_recent_context`, `get_continuity_context`.

References:
- `src/psychoanalyst_app/agents/trio_memory_agent.py`

## Inputs
- `Session` transcript for analysis.
- `LLMService`, `RAGService`, `TrioDatabaseService`.
- `UserContext` for user-level session retrieval.

## Outputs
- `SessionContext` with themes, emotional state, insights, progress indicators.
- `TherapeuticMemory` aggregates across sessions.
- Pattern and continuity summaries for downstream agents.

## Structured Output Examples

StructuredUserProfileOutput (not emitted by memory; shown for reference):

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

StructuredTherapyPlanOutput (not emitted by memory; shown for reference):

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
- No direct persistence (read-only session access).
- Caches memory for up to one hour to reduce repeated work.

## Dependencies
- Prompt builder: `psychoanalyst_app/prompts/memory_prompt_builder.py`.
- Structured output model: `SessionAnalysis`.

## Failure Modes and Fallbacks
- Raises `MemoryError` on structured output mismatch or analysis failures.
- Falls back to rebuilding memory when cache is stale.

## Removal Impact
- Planning and reflection lose context and longitudinal insights.
- Therapy style recommendations and plan updates degrade.

## Observability and Testing Notes
- Logs record memory cache usage and session analysis outcomes.
