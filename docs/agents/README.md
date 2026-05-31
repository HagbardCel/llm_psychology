---
owner: engineering
status: active
last_reviewed: 2026-02-14
review_cycle_days: 90
source_of_truth_for: Agent responsibilities, workflow routing, and orchestration integration contract
---

# Agent Documentation

This section documents each agent's contract, triggers, and responsibilities.
It is intended to be the authoritative reference for how agent logic fits into
workflow orchestration and persistence.

## Where Agents Run in the Workflow

Workflow state to agent routing is defined in
`src/psychoanalyst_app/orchestration/trio_workflow_engine.py`.
The orchestrator uses this mapping to pick the agent on each user message.

| Workflow state | Agent type | Primary agent class |
| --- | --- | --- |
| NEW | INTAKE | `TrioIntakeAgent` |
| INTAKE_IN_PROGRESS | INTAKE | `TrioIntakeAgent` |
| INTAKE_COMPLETE | ASSESSMENT | `TrioAssessmentAgent` |
| ASSESSMENT_IN_PROGRESS | ASSESSMENT | `TrioAssessmentAgent` |
| ASSESSMENT_COMPLETE | THERAPIST | `TrioTherapistAgent` |
| THERAPY_IN_PROGRESS | THERAPIST | `TrioTherapistAgent` |
| REFLECTION_IN_PROGRESS | REFLECTION | `TrioReflectionAgent` |
| PLAN_UPDATE_COMPLETE | THERAPIST | `TrioTherapistAgent` |

## Execution Pipeline (High Level)

1. `TrioAgentOrchestrator.process_message` resolves the current state and
   retrieves the agent instance.
2. The agent returns an `AgentResponse` (content + next_action + metadata).
3. The orchestrator streams content via `TrioConversationManager`.
   If `metadata.is_direct_response` is true, the response bypasses the LLM.
4. `finalize_agent_response` and `AgentResponseHandler.handle` persist outputs
   and perform workflow transitions.

References:
- `src/psychoanalyst_app/orchestration/trio_agent_orchestrator.py`
- `src/psychoanalyst_app/orchestration/process_messages.py`
- `src/psychoanalyst_app/orchestration/response_handler.py`

## Workflow Sequence Diagram (Foreground + Background Jobs)

```mermaid
sequenceDiagram
    participant User
    participant Orchestrator as TrioAgentOrchestrator
    participant Agent as Agent (INTAKE/ASSESSMENT/THERAPIST/REFLECTION)
    participant Conv as TrioConversationManager
    participant Handler as AgentResponseHandler
    participant WF as TrioWorkflowEngine
    participant Jobs as Background Jobs
    participant DB as TrioDatabaseService

    User->>Orchestrator: message
    Orchestrator->>WF: get_user_state
    Orchestrator->>Agent: process_message(context)
    Agent-->>Orchestrator: AgentResponse
    Orchestrator->>Conv: stream_response
    Orchestrator->>Handler: handle(response)
    Handler->>WF: transition (if workflow_event)

    alt Intake complete
        Handler->>Jobs: ensure_assessment_job
        Jobs->>Agent: process_assessment(context)
        Jobs->>Conv: emit assessment_recommendations
        Jobs->>WF: transition to ASSESSMENT_COMPLETE
    end

    alt Session complete
        Handler->>Jobs: ensure_reflection_job
        Jobs->>Agent: process_reflection(session)
        Jobs->>DB: persist plan/profile/tier updates
        Jobs->>WF: transition to PLAN_UPDATE_COMPLETE
    end
```

## Background Jobs (Non-Interactive)

Some agents are triggered by workflow events rather than a direct user message:

- Assessment recommendations are produced by a background job started when
  intake completes: `AgentResponseHandler.ensure_assessment_job`.
- Reflection runs after a therapy session completes and can update plans,
  Tier 2 enrichment, and Tier 3 analysis: `AgentResponseHandler.ensure_reflection_job`.

## Structured Outputs and Persistence

- User profile updates are normalized by `build_user_profile_output` and saved
  in `finalize_agent_response`.
- Therapy plan outputs are built by planning/reflection and persisted after
  reflection completes.
- Tier 2 and Tier 3 updates are persisted in the reflection job handler.

References:
- `src/psychoanalyst_app/orchestration/agent_output_validators.py`
- `src/psychoanalyst_app/orchestration/process_messages.py`
- `src/psychoanalyst_app/orchestration/response_handler.py`
- `src/psychoanalyst_app/orchestration/persistence.py`

## Per-Agent Docs

- [TrioIntakeAgent](trio_intake_agent.md)
- [TrioAssessmentAgent](trio_assessment_agent.md)
- [TrioTherapistAgent](trio_therapist_agent.md)
- [TrioReflectionAgent](trio_reflection_agent.md)
- [TrioPlanningAgent](trio_planning_agent.md)
- [TrioMemoryAgent](trio_memory_agent.md)
