# Session Check-In and Session Planning Implementation Plan

## Goals
- Add a distinct, time-boxed check-in phase at the start of therapy sessions.
- Use the existing session briefing to ground the check-in and continuity.
- Always generate an internal session plan that aligns with the long-term therapy plan.
- Store the check-in transcript and the session plan in separate session fields.
- Keep prompts and outputs deterministic enough for a junior developer to implement.

## Non-Goals
- Exposing the session plan to the client UI by default (internal only).
- Adding UI markers for phases (not needed because fields are separate).
- Changing the overall therapy plan update cadence (still handled in reflection).

## Workflow Overview (High-Level)
1. User enters a therapy session (state: PLAN_COMPLETE or ASSESSMENT_COMPLETE).
2. Orchestrator transitions the user to CHECKIN_IN_PROGRESS and routes to Check-in Agent.
3. Check-in Agent:
   - Uses session briefing to briefly remind the patient of last session.
   - Asks how they have been feeling and what they want to discuss today.
   - Time-boxes the exchange (max 5 minutes; shorter if little input).
4. Check-in summary is generated (structured) and passed to Planning Agent.
5. Planning Agent creates a Session Plan using:
   - Check-in summary
   - Therapy plan + current status
   - Session briefing (explicitly required)
6. Orchestrator transitions to THERAPY_IN_PROGRESS and routes to Psychoanalyst Agent.
7. Psychoanalyst Agent uses the Session Plan to guide the session and can verbalize a short intent line ("Today I would like to explore...").
8. On persistence, the session record includes:
   - checkin_transcript
   - session_plan
   - therapy transcript (as today)

## Detailed Requirements
- Check-in is a distinct agent (TrioCheckinAgent).
- Check-in ends quickly if the patient has little feedback.
- Check-in must end after 5 minutes even if the patient has more to say.
- Session plan is always generated (no skipping).
- Session plan is internal only, but the therapist can reference it briefly in speech.
- Session briefing must be considered in the session plan.
- Check-in transcript must be persisted in a separate field.

## Proposed Data Model Changes
### New Models
- StructuredSessionPlanOutput (new structured output model)
  - session_focus: str
  - immediate_goals: list[str] (1-3 items)
  - planned_interventions: list[str] (1-3 items)
  - themes_to_revisit: list[str] (0-3 items)
  - risks_or_watchouts: list[str] (0-3 items)
  - suggested_opening: str (optional; used by therapist)
  - alignment_note: str (1-2 sentences on how this supports the therapy plan)

- CheckinSummary (internal helper model; not necessarily persisted)
  - current_state: str
  - new_or_urgent_topics: list[str]
  - patient_requested_focus: str | None
  - mood_snapshot: str
  - readiness_level: str ("low" | "medium" | "high")

### Session Model Changes
Add fields to `Session` in `src/psychoanalyst_app/models/data_models.py`:
- checkin_transcript: list[Message] (default empty)
- session_plan: dict[str, Any] | None

### HTTP/WS DTO Updates
Update `src/psychoanalyst_app/models/http_models.py` and schema generation:
- Include `checkin_transcript` and `session_plan` in session responses.
- Ensure `session_plan` is optional for legacy sessions.

## Workflow and State Changes
### New Workflow State
Add `CHECKIN_IN_PROGRESS` in `src/psychoanalyst_app/orchestration/models.py`:
- Add to `WorkflowState` enum.
- Add to workflow engine mapping in `src/psychoanalyst_app/orchestration/trio_workflow_engine.py`.
- Add corresponding `UserStatus.CHECKIN_IN_PROGRESS` in `src/psychoanalyst_app/models/data_models.py`.

### New Workflow Event
Add `COMPLETE_CHECKIN` (and optionally `START_CHECKIN`) in `WorkflowEvent`:
- The check-in agent emits `COMPLETE_CHECKIN` when it wraps up.
- Workflow transition goes to `THERAPY_IN_PROGRESS`.

### Next Action Resolver
Update `src/psychoanalyst_app/orchestration/workflow_next_action.py`:
- Treat CHECKIN_IN_PROGRESS similar to therapy (required_action: CONTINUE_THERAPY).
- Ensure session auto-start can transition into check-in.

## New Check-In Agent
### Responsibilities
- Generate an opening check-in prompt using the session briefing.
- Ask about current well-being and desired topics.
- Time-box to 5 minutes.
- End early if little input, especially if briefing is stale.
- Produce CheckinSummary + full checkin_transcript.

### Implementation Notes
- Create `src/psychoanalyst_app/agents/trio_checkin_agent.py`.
- Add documentation in `docs/agents/trio_checkin_agent.md`.
- Add prompt builder in `src/psychoanalyst_app/prompts/checkin_prompt_builder.py`.
- Use `session_briefing` fields (narrative, continuity points, suggested questions) to craft a short reminder.

### Timing Behavior
- Track `checkin_start_time` in ConversationContext or a new per-session timer.
- End check-in when:
  - elapsed_minutes >= 5
  - OR (briefing is stale AND user gives minimal feedback after 1-2 turns)
  - OR user explicitly says there is nothing to add

## Planning Agent Extension (Session Plan)
### New Method
Add `create_session_plan(...)` to `TrioPlanningAgent`:
- Inputs:
  - checkin_summary
  - current therapy_plan
  - session_briefing
  - therapy plan status + current progress
- Output:
  - StructuredSessionPlanOutput

### Prompt Guidance
- Tie every session plan to the therapy plan goals.
- If check-in is minimal, use session briefing + therapy plan to define focus.
- Always generate a plan (no short-circuit).

## Orchestrator Changes
- When a therapy session starts, set user state to CHECKIN_IN_PROGRESS.
- Route all initial messages to Check-in Agent until it emits COMPLETE_CHECKIN.
- On COMPLETE_CHECKIN:
  - Persist checkin_transcript to the session record.
  - Run Planning Agent to generate session plan.
  - Attach session_plan to the session record and context.
  - Transition to THERAPY_IN_PROGRESS and route to Psychoanalyst Agent.

## Psychoanalyst Agent Updates
- Include `session_plan` in the prompt context for therapy sessions.
- Allow a brief verbalization of intent ("Today I would like to explore...").
- Keep it internal and avoid exposing the plan verbatim.

## Persistence and Migrations
### Database
- Add columns to `sessions` table:
  - `checkin_transcript` (TEXT, JSON)
  - `session_plan` (TEXT, JSON)
- Update `src/psychoanalyst_app/services/db_serialization.py`:
  - Include new columns in SESSION_COLUMNS.
  - Serialize/deserialize JSON fields.
- Update `src/psychoanalyst_app/services/db/repos/sessions_repo.py`:
  - Insert/update new columns.

### Migration Script
- Add migration in `migrations/` to alter `sessions` table.

## Contracts and Schemas
- Update `docs/contracts/HTTP_API_CONTRACT.md` if session payloads change.
- Regenerate schemas and frontend types:
  - `docker compose run --rm api python scripts/generate_schemas.py`
  - `docker compose run --rm frontend npm run generate:types`

## Testing Plan
### Unit Tests
- New tests for Check-in Agent timing and output.
- Planning Agent session plan output validation.
- Serialization tests for new session fields.

### Integration Tests
- Full therapy flow: check-in -> session plan -> therapy -> reflection.
- Confirm session_plan and checkin_transcript persistence.

## Acceptance Criteria
- Check-in ends within 5 minutes or sooner if minimal input.
- Session plan is always generated and stored.
- Session briefing influences the session plan.
- Session record includes separate checkin_transcript and session_plan.
- Therapy session uses the session plan in prompts.

## Suggested File Touch List
- `src/psychoanalyst_app/orchestration/models.py`
- `src/psychoanalyst_app/orchestration/trio_workflow_engine.py`
- `src/psychoanalyst_app/orchestration/workflow_next_action.py`
- `src/psychoanalyst_app/agents/trio_checkin_agent.py` (new)
- `src/psychoanalyst_app/prompts/checkin_prompt_builder.py` (new)
- `src/psychoanalyst_app/agents/trio_planning_agent.py`
- `src/psychoanalyst_app/agents/trio_psychoanalyst_agent.py`
- `src/psychoanalyst_app/models/data_models.py`
- `src/psychoanalyst_app/models/structured_output_models.py`
- `src/psychoanalyst_app/services/db_serialization.py`
- `src/psychoanalyst_app/services/db/repos/sessions_repo.py`
- `docs/agents/trio_checkin_agent.md` (new)
- `docs/contracts/HTTP_API_CONTRACT.md`

