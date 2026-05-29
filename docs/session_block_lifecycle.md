# Session Block Lifecycle Documentation

> [!WARNING]
> Deprecated on 2026-02-14. This document uses legacy `SessionBlock` / `session_block_id`
> terminology and is kept only for historical context. The canonical lifecycle is
> `docs/session_lifecycle.md` with `Session` and `session_id`.

This document describes the chronological flow of a clinical session block within the application, detailing agent activation, data checks, and database persistence.

## 1. Session Block Initialization

### 1.1. Client Session (WebSocket Connection)

The interaction begins when a client connects to the WebSocket endpoint (`/ws?user_id=<user_id>`). This establishes a **Client Session**.

- **Entry Point:** WebSocket handler in `src/psychoanalyst_app/api/ws_handler.py`
  (registered by `TrioServer` in `src/psychoanalyst_app/trio_server.py`).
- **User Check:** The system checks `trio_db_service` for an existing `UserProfile`.
- **Missing Profile:** The server sends an `error` event and closes the connection.
- **Requirement:** Clients must call `POST /api/user/register` or `POST /api/user/login` before connecting to WS.

### 1.2. Session Block Start (Auto)

On WebSocket connect, the server auto-creates or resumes the correct **Session Block**
based on the user's workflow state. A Session Block represents a distinct unit of clinical work (e.g., an Intake session, a Therapy session).

- **Action:** `TrioAgentOrchestrator.ensure_session_block_for_user(...)` is called.
- **Session Block Creation:**
  - A new `SessionBlock` object is created with a unique UUID.
  - **Persistence:** The session block is saved to the `session_blocks` table in the database.
- **Initial Greeting:**
  - The orchestrator evaluates `workflow_next_action` after session block start.
  - If `required_action` is not `wait`, it triggers an "initial greeting" by sending an empty message to the active agent.
  - If `required_action` is `wait`, the greeting is skipped and the wait prompt is used as the status notice.

## 2. Active Session Block Workflow

The interaction flow is driven by the **Orchestrator**, which routes user messages to the appropriate **Agent** based on the user's **Workflow State**.

### 2.1. The Orchestrator (`TrioAgentOrchestrator`)

- **Role:** Central router and state manager.
- **Process:**
  1.  Receives user message via WebSocket (Client Session).
  2.  Persists message to `SessionBlock` transcript.
  3.  Determines current `WorkflowState` (e.g., `INTAKE_IN_PROGRESS`, `ASSESSMENT_IN_PROGRESS`).
  4.  Instantiates the correct agent (`Intake`, `Assessment`, etc.).
  5.  Delegates message processing to the agent.
  6.  Streams the agent's textual response back to the user.
  7.  Handles state transitions based on agent `workflow_event` signals (orchestrator-owned).

### 2.2. Phase 1: Intake (`TrioIntakeAgent`)

**Active when State = `NEW` or `INTAKE_IN_PROGRESS`**

- **Role:** Collects basic user information and understands the presenting problem.
- **Key Activities:**
  - **Profile Check:** Registration ensures required profile fields are already present.
  - **Topic Tracking:** Analyzes every message for keywords related to `INTAKE_TOPICS` (e.g., "Family", "Symptoms", "Work").
  - **Completion Check:** Monitors if sufficient topics (≥80%) have been covered or if time is up.
- **Data Persistence:**
  - Updates `UserProfile.name`.
  - Orchestrator updates `UserProfile.status` as workflow events are accepted.

### 2.3. Phase 2: Assessment (`TrioAssessmentAgent`)

**Active when State = `INTAKE_COMPLETE` or `ASSESSMENT_IN_PROGRESS`**

- **Role:** Analyzes the intake session and recommends formatted therapy styles.
- **Key Activities:**
  - **Recommendation Generation:** Uses LLM to assess the intake transcript against known therapy styles (e.g., Freud, Jung, CBT).
  - **Presentation:** Emits `assessment_recommendations` over WebSocket.
  - **Backend Job:** Runs asynchronously after the workflow transitions to `INTAKE_COMPLETE`; clients display a wait state.
- **Data Persistence:**
  - **Therapy Plan:** Created only after the user completes
    `POST /api/workflow/select_therapy_style`.
  - **State Update:** Transitions user to `ASSESSMENT_COMPLETE` when the job finishes.

### 2.4. Phase 3: Therapy (`TrioPsychoanalystAgent` - _implied_)

**Active when State = `THERAPY_IN_PROGRESS`**

- **Role:** Conducts actual therapy sessions based on the selected plan.
- **Key Activities:**
  - Engages in therapeutic dialogue.
  - Updates session block topics and transcript.
- **Data Persistence:**
  - Continually updates `SessionBlock` transcript in `session_blocks` table.

### 2.5. Phase 4: Reflection (`TrioReflectionAgent`)

**Active when State = `REFLECTION_IN_PROGRESS`**

- **Trigger:** Automatically activated when the `PsychoanalystAgent` detects the session time is up (`context.is_time_up`).
- **Role:** Analyzes the completed session, generates insights, and prepares for the next session.
- **Key Activities:**
  - **Session Analysis:** Uses `TrioMemoryAgent` to extract key themes and emotional states.
  - **Plan Update:** Uses `TrioPlanningAgent` to assess plan effectiveness and recommend adjustments.
  - **Briefing Generation:** Creates a comprehensive `SessionBriefing` for the next session (critical for continuity).
- **Data Persistence:**
  - **Therapy Plan:** Updates `TherapyPlan` with new version, plan details, and `session_briefing`.
  - **State Update:** Transitions user to `PLAN_UPDATE_COMPLETE` (ready for next session).

### 2.6. Session Continuity (The Loop)

The system ensures continuity between sessions using the `SessionBriefing` object.

- **Generation:** Created by `ReflectionAgent` at the end of Session N.
- **Storage:** Saved within the `TherapyPlan`.
- **Consumption:** Used by `PsychoanalystAgent` at the start of Session N+1.
- **Mechanism:**
  - When starting a new session, the agent checks for a valid `session_briefing`.
  - If found, it generates a **Resumption Prompt** instead of a generic greeting.
  - This prompt includes:
    - **Narrative Handoff:** A summary of where the last session left off.
    - **Key Themes:** Unresolved issues or high-priority topics to revisit.
    - **Emotional Trajectory:** Context on the user's emotional state.
    - **Suggested Questions:** Tailored opening questions for the therapist.
  - **Staleness Check:** If the briefing is too old (> 7 days), the prompt is adjusted to be more exploratory, acknowledging the time gap.

## 3. Session Closure

The session can be closed in two ways:

### 3.1. Explicit Closure

- **Trigger:** An agent returns an `end_session` action (e.g., user says "I'm done for now").
- **Action:** The Orchestrator transitions workflow state, runs any follow-up jobs
  (assessment/reflection), then emits `session_ended` and expects the client to terminate.
- **Persistence:** The final state of the session transcript is saved.

### 3.2. WebSocket Disconnection

- **Trigger:** Client disconnects.
- **Action:** `TrioServer`'s `finally` block cleans up the orchestrator connection.
- **Persistence:** Any pending session data is flushed to the database.

## 4. Database Schema Summary

Data is persisted in `data/psychoanalyst.db` (SQLite) via `TrioDatabaseService`.

| Table               | Key Content                                         | Updated By                        |
| :------------------ | :-------------------------------------------------- | :-------------------------------- |
| **`session_blocks`**| `session_block_id`, `transcript` (JSON), `topics`   | All Agents (per message)          |
| **`user_profiles`** | `name`, `status` (Workflow State), `profession`     | Intake Agent, Orchestrator        |
| **`therapy_plans`** | `selected_therapy_style`, `plan_details`, `version` | Planning Agent (via Reflection) |
