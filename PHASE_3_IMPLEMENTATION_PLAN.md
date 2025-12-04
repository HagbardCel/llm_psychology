# Phase 3 Implementation Plan: Feature Completion (User Journey)

## Goal

Implement the complete user journey workflow, including Profile creation, Intake, Assessment, and Therapy sessions, ensuring full compatibility with the backend's `Trio` agent architecture.

## User Review Required

> [!IMPORTANT]
> This phase transforms the application from a simple chat interface into a full workflow-driven application.
> **Key Architectural Decision:** The `Intake` and `Assessment` phases will utilize the existing `TherapySession` chat interface but with specialized wrappers and context, as these agents operate primarily through conversation.

## Prerequisites

- Phase 0 (Blockers) & Phase 1 (Integration) complete.
- Phase 2 (Testing Foundation) complete.
- Backend running `trio_server.py`.

## Proposed Changes

### 1. Navigation & Routing Infrastructure

#### [NEW] [src/components/NavigationDrawer.tsx](file:///app/frontend/src/components/NavigationDrawer.tsx)

- **Purpose:** Main navigation menu.
- **Features:**
  - Links to: Dashboard, Current Session, History, Profile, Settings.
  - Dynamic items based on `UserStatus` (e.g., lock "Therapy" until Assessment complete).
  - User profile summary (Avatar/Name) at top.

#### [MODIFY] [src/components/Layout.tsx](file:///app/frontend/src/components/Layout.tsx) (or create if missing)

- Wrap application in a standard layout with `AppBar` and `NavigationDrawer`.
- Ensure responsive behavior (drawer toggles on mobile).

#### [MODIFY] [src/App.tsx](file:///app/frontend/src/App.tsx)

- Implement **Route Guards**:
  - `RequireAuth`: Redirect to Profile/Login if no user.
  - `RequireStatus`: Redirect to appropriate workflow step (e.g., if `INTAKE_IN_PROGRESS`, redirect to `/intake`).
- Define routes:
  - `/profile`: ProfilePage
  - `/intake`: IntakePage
  - `/assessment`: AssessmentPage
  - `/session/:sessionId`: TherapySessionPage
  - `/dashboard`: DashboardPage
  - `/settings`: SettingsPage

### 2. Profile Management

#### [NEW] [src/pages/ProfilePage.tsx](file:///app/frontend/src/pages/ProfilePage.tsx)

- **Purpose:** User onboarding and profile editing.
- **Features:**
  - Form fields: Name, Age, Profession, Goals (optional).
  - **Integration:**
    - GET `/api/user/:id` to load.
    - POST/PUT `/api/user/:id` to save.
    - Updates `AuthContext` user state.

### 3. Intake Workflow

#### [NEW] [src/pages/IntakePage.tsx](file:///app/frontend/src/pages/IntakePage.tsx)

- **Purpose:** Interface for `TrioIntakeAgent`.
- **Implementation:**
  - Wraps `TherapySession` component.
  - **Configuration:**
    - Sets `agentType` to `AgentType.INTAKE`.
    - Shows specific "Intake in Progress" header.
  - **Transition:**
    - Listens for `UserStatus` change to `INTAKE_COMPLETE`.
    - Shows "Proceed to Assessment" button when complete.

### 4. Assessment & Style Selection

#### [NEW] [src/pages/AssessmentPage.tsx](file:///app/frontend/src/pages/AssessmentPage.tsx)

- **Purpose:** Interface for `TrioAssessmentAgent` and Style Selection.
- **Implementation:**
  - **Split View / Mode:**
    1.  **Chat Mode:** Wraps `TherapySession` (Agent: `ASSESSMENT`) for the analysis conversation.
    2.  **Selection Mode:** Triggered when agent recommends styles.
  - **Style Selection UI:**
    - Cards for recommended styles (Freud, Jung, CBT).
    - "Why this style?" explanation (from Agent).
    - "Select Style" button.
  - **Integration:**
    - Sends `style_selected` event via WebSocket.
    - Updates `TherapyPlan`.

### 5. Settings & Preferences

#### [NEW] [src/pages/SettingsPage.tsx](file:///app/frontend/src/pages/SettingsPage.tsx)

- **Features:**
  - Theme toggle (Light/Dark).
  - Font size adjustment.
  - "Danger Zone": Reset Progress / Clear Data.

### 6. Dashboard Integration

#### [MODIFY] [src/components/Dashboard.tsx](file:///app/frontend/src/components/Dashboard.tsx)

- **Workflow Visualization:**
  - Stepper component showing: Profile -> Intake -> Assessment -> Therapy.
  - Active step highlighted based on `UserStatus`.
- **Action Button:**
  - Dynamic "Continue" button routing to the current workflow step.

## Verification Plan

### Automated Tests

- **Navigation:** Test `NavigationDrawer` rendering and link states.
- **Routing:** Test `RequireStatus` guard redirects correctly based on mock user status.
- **Profile:** Test form validation and API submission.
- **Intake/Assessment:** Test wrapper components pass correct props to `TherapySession`.

### Manual Verification

1.  **Full User Journey Walkthrough:**
    - **Start:** Clear localStorage. Reload.
    - **Profile:** Verify redirected to Profile. Create user.
    - **Intake:** Verify redirected to Intake. Chat with Intake Agent.
    - **Assessment:** Complete Intake. Verify transition to Assessment. Chat with Assessment Agent.
    - **Selection:** Select a therapy style.
    - **Therapy:** Verify redirected to main Therapy Session.
2.  **Persistence:** Reload at each stage; verify user remains on correct step.
3.  **Responsiveness:** Test Navigation Drawer on mobile view.

## Timeline Estimate

- **Days 1-2:** Navigation, Routing, Profile Page.
- **Days 3-4:** Intake & Assessment Pages (Workflow logic).
- **Day 5:** Settings & Dashboard Integration.
