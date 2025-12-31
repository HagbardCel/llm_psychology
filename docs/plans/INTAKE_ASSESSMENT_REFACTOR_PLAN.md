# Intake to Assessment Refactoring Plan

## 1. Executive Summary
This plan outlines the architectural refactoring of the user onboarding process. We will transition from a Conversational Intake Agent to a **Form-Based Registration Flow** followed by an **Interactive Assessment Agent**.

### Motivation
*   **Data Integrity:** LLMs struggle with precise data entry (spelling, dates). A structured form guarantees accurate user profiles.
*   **Contextual Intelligence:** By capturing profile data upfront, the LLM can start the first conversation with deep context ("I see you are a teacher...") rather than generic questions.
*   **Cost & Latency:** Removing the "chat-to-profile" extraction step reduces token usage and speeds up the initial experience.
*   **Clinical Flow:** mimics real-world therapy where patients fill out intake forms before meeting the therapist.

### Goals
1.  **Eliminate `TrioIntakeAgent`:** Replace it with a frontend registration form and API endpoint.
2.  **Enhance `TrioAssessmentAgent`:** Upgrade it to handle the active clinical interview, using the pre-filled profile data.
3.  **Capture "Presenting Problem":** Include a free-text field in the registration form for the user's primary motivation for therapy.

---

## 2. Architecture Changes

### A. New Workflow State
*   **Current:** `NEW` → `INTAKE_IN_PROGRESS` → `INTAKE_COMPLETE` → `ASSESSMENT_...`
*   **New:** `NEW` (No Profile) → `PROFILE_COMPLETE` (Profile Exists) → `ASSESSMENT_IN_PROGRESS` (First Chat)

### B. Component Shifts
| Component | Old Responsibility | New Responsibility |
| :--- | :--- | :--- |
| **Frontend** | Chat interface for everything. | **Wizard/Form** for Profile → Chat for Assessment. |
| **Intake Agent** | Chatbot asking name/age/goals. | **REMOVED.** |
| **Assessment Agent** | Passive analysis of intake transcript. | **Active Interviewer** + Analyst. |
| **User Profile** | Built incrementally via chat. | **Pre-filled** via API before chat starts. |

---

## 3. Implementation Plan

### Phase 1: Backend API & Data Model (The "Form" Handler)

**Objective:** Allow creating a full user profile via a single API call.

1.  **Update `UserProfile` Model**
    *   Ensure the model supports all form fields:
        *   `name` (str)
        *   `age` (int) - *New/Verify*
        *   `profession` (str) - *New/Verify*
        *   `gender` (str)
        *   `presenting_issue` (str) - **CRITICAL NEW FIELD** (The "Reason for visit")
    *   *File:* `src/psychoanalyst_app/models/data_models.py`

2.  **Update/Create Profile Endpoint**
    *   Update `POST /api/user/profile` to accept the full payload.
    *   **Logic:**
        *   Validate input.
        *   Save to DB.
        *   **Trigger State Transition:** Automatically move user from `NEW` to `ASSESSMENT_IN_PROGRESS` (skipping `INTAKE`).
    *   *File:* `src/psychoanalyst_app/api/user_routes.py`

3.  **Remove Intake Agent**
    *   Delete `src/psychoanalyst_app/agents/trio_intake_agent.py`.
    *   Remove from `TrioAgentOrchestrator` and `TrioWorkflowEngine`.
    *   Remove `INTAKE_IN_PROGRESS` and `INTAKE_COMPLETE` states from `WorkflowState` enum.
    *   *Files:* `src/psychoanalyst_app/orchestration/trio_workflow_engine.py`, `src/psychoanalyst_app/orchestration/models.py`.

### Phase 1.5: Workflow & Action Mapping Refactor (The "Logic Bridge")

**Objective:** Align the Orchestrator's decision-making with the new states. The current mapping relies on "Intake" states that will no longer exist.

**Motivation:**
*   The system currently relies on a chain: `NEW` -> `INTAKE` -> `ASSESSMENT`.
*   Breaking this chain requires "rewiring" the logic so the system knows that a `PROFILE_COMPLETE` user is immediately ready for `ASSESSMENT`.
*   `resolve_next_action` currently looks for `INTAKE` states to prompt the user. It must be updated to recognize that the *first* chat action happens in `ASSESSMENT`.

1.  **Update `TrioWorkflowEngine` Map**
    *   **Remove:** `INTAKE` mappings.
    *   **Update:**
        ```python
        STATE_AGENT_MAP = {
            # WorkflowState.NEW: "INTAKE",  <-- REMOVE
            WorkflowState.ASSESSMENT_IN_PROGRESS: "ASSESSMENT",
            # ... others remain
        }
        ```
    *   **Transitions:**
        *   Allow `NEW` -> `ASSESSMENT_IN_PROGRESS` (triggered by Profile API).

2.  **Refactor `workflow_next_action.py`**
    *   **Logic Update:**
        *   **IF** `profile` is incomplete -> Return `COMPLETE_PROFILE` (remains same).
        *   **IF** `profile` is complete AND state is `NEW` -> **Auto-transition** (or prompt) to `START_ASSESSMENT`.
        *   **Remove** checks for `INTAKE_IN_PROGRESS` / `INTAKE_COMPLETE`.
        *   Update `_start_session_action` to point users directly to the Assessment chat.

### Phase 2: Assessment Agent Upgrade (The "Interviewer")

**Objective:** The Assessment Agent must now *conduct* the interview, not just analyze it.

1.  **Update `TrioAssessmentAgent.process_message`**
    *   **Logic Branching:**
        *   **IF** (Conversation History is Empty): Generate **Opening Hook**.
            *   *Prompt:* "You are meeting {name}, a {age}-year-old {profession}. They are here because: '{presenting_issue}'. Welcome them warmly and ask a relevant follow-up question to explore their issue."
        *   **IF** (Sufficient Information Gathered): Generate **Recommendations** (Existing logic).
        *   **ELSE**: Continue **Exploration**.
            *   *Prompt:* "Continue exploring the patient's background, family history, and symptoms based on their profile and recent answers."
    *   *File:* `src/psychoanalyst_app/agents/trio_assessment_agent.py`

2.  **Prompt Engineering**
    *   Create `ASSESSMENT_INTERVIEW_PROMPT`.
    *   Inputs: `user_profile` (including `presenting_issue`), `conversation_history`.
    *   Goal: "Act as a clinical interviewer. Be empathetic but analytical. Do not solve the problem yet; diagnose the structure of the problem."
    *   *File:* `src/psychoanalyst_app/prompts/assessment_prompts.py`

### Phase 3: Frontend Implementation (The UI)

**Objective:** Guide the user through the form before showing the chat.

1.  **New Registration Component**
    *   Create `src/components/RegistrationForm.tsx`.
    *   Fields: Name, Age, Gender, Profession, **"What brings you here today?" (Text Area)**.
    *   Submit Button: POST to `/api/user/profile`.

2.  **App Routing / State Management**
    *   On App Load: Check User Status (`GET /api/user/status`).
    *   **IF** `status == NEW`: Show `RegistrationForm`.
    *   **IF** `status == ASSESSMENT_IN_PROGRESS` (or later): Show `ChatInterface`.

---

## 4. Verification & Testing

### Test Scenarios
1.  **Happy Path:**
    *   User loads page → Sees Form.
    *   Fills Form (inc. "Anxiety about work") → Submits.
    *   Backend saves Profile → Sets State to `ASSESSMENT_IN_PROGRESS`.
    *   Frontend transitions to Chat.
    *   **First Message:** Agent says "Hello [Name], I see you're struggling with work anxiety. Can you tell me more about when this started?" (Verifies Context Injection).

2.  **Edge Cases:**
    *   User refreshes page during Assessment (Should stay in Chat).
    *   User submits empty form (Validation check).

### Success Metrics
*   **Zero Token Waste:** No tokens spent extracting "My name is Bob" from chat.
*   **Immediate Depth:** First AI response references specific profile details.
*   **Code Cleanup:** `TrioIntakeAgent` is completely gone.

## 5. Timeline Estimate (Junior Developer)
*   **Day 1:** Backend Data Models & API Endpoints.
*   **Day 2:** Frontend Registration Form & Routing Logic.
*   **Day 3:** Assessment Agent Logic Updates & Prompting.
*   **Day 4:** Testing, Cleanup, and Polish.
