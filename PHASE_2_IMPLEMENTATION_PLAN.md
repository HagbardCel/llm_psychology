# Phase 2 Implementation Plan: Feature Completion

## Goal

Implement the missing core pages and navigation structure to complete the user journey from profile creation to therapy assessment.

## User Review Required

> [!IMPORTANT]
> This phase involves creating multiple new pages and components.
> I will be implementing the "Intake" and "Assessment" flows which are currently placeholders.

## Proposed Changes

### 1. Navigation & Layout

#### [NEW] [src/components/NavigationDrawer.tsx](file:///app/frontend/src/components/NavigationDrawer.tsx)

- Create a side drawer component using MUI `Drawer`.
- Include links to: Home, Session, History, Progress, Settings.
- Show current user info at the top.

#### [MODIFY] [src/components/TherapySession.tsx](file:///app/frontend/src/components/TherapySession.tsx)

- Integrate `NavigationDrawer`.
- Wire up the menu button to open the drawer.

### 2. Core Pages

#### [NEW] [src/pages/ProfilePage.tsx](file:///app/frontend/src/pages/ProfilePage.tsx)

- Form to edit user profile (name, profession, birthdate).
- Save to backend via API.

#### [NEW] [src/pages/IntakePage.tsx](file:///app/frontend/src/pages/IntakePage.tsx)

- Interface for the Intake Agent flow.
- Display intake questions and handle responses.
- Transition to Assessment upon completion.

#### [NEW] [src/pages/AssessmentPage.tsx](file:///app/frontend/src/pages/AssessmentPage.tsx)

- Interface for the Assessment Agent flow.
- Display therapy style options (Freud, Jung, CBT).
- Allow style selection and plan creation.

#### [NEW] [src/pages/SettingsPage.tsx](file:///app/frontend/src/pages/SettingsPage.tsx)

- User preferences (theme, notifications).
- Account management (logout).

### 3. Routing

#### [MODIFY] [src/App.tsx](file:///app/frontend/src/App.tsx)

- Update routes to point to the new page components instead of placeholders.
- Add `AuthGuard` (optional, if time permits) to protect routes.

## Verification Plan

### Automated Tests

- **New Test:** `src/components/__tests__/NavigationDrawer.test.tsx`
  - Verify links render and navigation works.
- **New Test:** `src/pages/__tests__/ProfilePage.test.tsx`
  - Verify form submission.

### Manual Verification

1.  **Navigation:**
    - Open the app.
    - Click the menu button.
    - Verify drawer opens and links work.
2.  **Profile Flow:**
    - Navigate to `/profile`.
    - Update profile information.
    - Verify changes are saved (persist on reload).
3.  **Intake Flow:**
    - Navigate to `/intake`.
    - Verify the intake UI loads.
4.  **Settings:**
    - Navigate to `/settings`.
    - Toggle a setting (e.g., theme if implemented).
