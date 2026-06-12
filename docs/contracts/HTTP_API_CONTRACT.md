---
owner: engineering
status: active
last_reviewed: 2026-05-31
review_cycle_days: 90
source_of_truth_for: HTTP wire contract and DTO shape guarantees
---

# HTTP API Contract (Phase 1)

This document is the authoritative HTTP contract for Phase 1 (“Contract Stabilization”).

## Global Rules

- **Key naming**: `snake_case` for all JSON keys.
- **Datetime encoding**: ISO 8601 strings (timezone offset or `Z` recommended).
- **Errors**: JSON body with a single `error` string.
  - Shape: `{ "error": "<message>" }`

## DTOs (Wire Shapes)

These shapes are what all clients should assume on the wire.

### `UserProfileDTO`

- `user_id`: `string`
- `name`: `string`
- `alias`: `string | null`
- `date_of_birth`: `string | null` (ISO 8601)
- `gender`: `string | null`
- `cultural_background`: `string | null`
- `primary_language`: `string`
- `profession`: `string | null`
- `status`: `string` (enum value)
- `plan_id`: `string | null`
- `parents`: `string | null`
- `siblings`: `string | null`
- `family_atmosphere`: `string | null`
- `significant_events`: `string | null`
- `education`: `string | null`
- `work_history`: `string | null`
- `relationship_to_work`: `string | null`
- `relationships`: `string | null`
- `social_context`: `string | null`
- `current_situation`: `string | null`
- `preferred_school`: `string | null`
- `boundary_notes`: `string | null`
- `frame_notes`: `string | null`
- `created_at`: `string` (ISO 8601)
- `updated_at`: `string` (ISO 8601)

### `UserProfileSummaryDTO`

- `user_id`: `string`
- `name`: `string`
- `status`: `string` (enum value)
- `primary_language`: `string`
- `plan_id`: `string | null`
- `updated_at`: `string` (ISO 8601)

### `UserProfileListResponseDTO`

- `profiles`: `UserProfileSummaryDTO[]`

### `MessageDTO`

- `role`: `string`
- `content`: `string`
- `timestamp`: `string` (ISO 8601)
- `agent`: `string | null`

### `TopicDTO`

- `name`: `string`
- `status`: `string`

### `SessionDTO`

- `session_id`: `string`
- `user_id`: `string`
- `session_type`: `"intake" | "therapy"`
- `plan_id`: `string | null`
- `timestamp`: `string` (ISO 8601)
- `transcript`: `MessageDTO[]`
- `topics`: `TopicDTO[]`
- `session_summary`: `string | null`
- `session_briefing`: `object | null`
- `psychological_summary`: `string | null`
- `dominant_affects`: `string[]`
- `key_themes`: `string[]`
- `notable_interactions`: `string | null`
- `interpretations`: `string | null`
- `patient_reactions`: `string | null`
- `enriched`: `boolean`

### `TherapyPlanDTO`

- `plan_id`: `string`
- `user_id`: `string`
- `created_at`: `string` (ISO 8601)
- `updated_at`: `string` (ISO 8601)
- `version`: `number`
- `supersedes_plan_id`: `string | null`
- `superseded_by_plan_id`: `string | null`
- `selected_therapy_style`: `string | null`
- `focus`: `string`
- `themes`: `string[]`
- `timeline`: `string | null`
- `initial_goals`: `string[]`
- `current_progress`: `string`
- `planned_interventions`: `string[]`
- `revision_recommendations`: `string[]`
- `status`: `"active" | "paused" | "completed" | "superseded"` (string)
- `session_briefing`: `object | null`

### `WorkflowNextActionDTO`

- `user_id`: `string`
- `workflow_state`: `string` (enum value matching `WorkflowState`: `new`, `intake_in_progress`, `intake_complete`, `assessment_in_progress`, `assessment_complete`, `initial_plan_complete`, `therapy_in_progress`, `plan_update_in_progress`, `reflection_in_progress`, `plan_update_failed`, `plan_update_complete`)
- `required_action`: `"complete_profile" | "select_therapy_style" | "start_intake" | "start_therapy" | "continue_therapy" | "retry_plan_update" | "wait"`
- `required_fields`: `string[]`
- `defaults`: `{ [k: string]: string } | null`
- `prompt`: `string | null`
- `blocking`: `boolean`
- `timestamp`: `string` (ISO 8601)
- `session_id`: `string | null`
- `state_signature`: `string` (stable across equivalent reevaluations)
- `emission_source`: `string | null` (set for pushed workflow events)

### `WorkflowCompleteProfileRequestDTO`

- `user_id`: `string`
- `session_id`: `string`
- `name`: `string`
- `alias`: `string | null`
- `date_of_birth`: `string | null` (ISO 8601)
- `gender`: `string | null`
- `cultural_background`: `string | null`
- `primary_language`: `string`
- `profession`: `string | null`
- `parents`: `string | null`
- `siblings`: `string | null`
- `family_atmosphere`: `string | null`
- `significant_events`: `string | null`
- `education`: `string | null`
- `work_history`: `string | null`
- `relationship_to_work`: `string | null`
- `relationships`: `string | null`
- `social_context`: `string | null`
- `current_situation`: `string | null`
- `preferred_school`: `string | null`
- `boundary_notes`: `string | null`
- `frame_notes`: `string | null`

### `CreateUserProfileRequestDTO`

- `user_id`: `string`
- `name`: `string`
- `alias`: `string | null`
- `date_of_birth`: `string | null` (ISO 8601)
- `gender`: `string | null`
- `cultural_background`: `string | null`
- `primary_language`: `string`
- `profession`: `string | null`
- `parents`: `string | null`
- `siblings`: `string | null`
- `family_atmosphere`: `string | null`
- `significant_events`: `string | null`
- `education`: `string | null`
- `work_history`: `string | null`
- `relationship_to_work`: `string | null`
- `relationships`: `string | null`
- `social_context`: `string | null`
- `current_situation`: `string | null`
- `preferred_school`: `string | null`
- `boundary_notes`: `string | null`
- `frame_notes`: `string | null`

### `UserLoginRequestDTO`

- `user_id`: `string`

### `UserRegisterResponseDTO`

- `session`: `SessionDTO`
- `workflow_next_action`: `WorkflowNextActionDTO`

### `WorkflowSelectTherapyStyleRequestDTO`

- `user_id`: `string`
- `session_id`: `string`
- `selected_therapy_style`: `string`

### `HealthCheckResponse`

- `status`: `"healthy" | "unhealthy"`
- `service`: `string`
- `database`: `"healthy" | "unhealthy"`
- `timestamp`: `string` (ISO 8601)

### `VersionInfoDTO`

- `api_version`: `string`
- `min_client_version`: `string`
- `server_time`: `string` (ISO 8601)

### `VersionCheckResponseDTO`

- `compatible`: `boolean`
- `api_version`: `string`
- `client_version`: `string`
- `message`: `string`
- `upgrade_required`: `boolean`
- `upgrade_recommended`: `boolean`

### `SessionTimerResponse`

- `session_id`: `string`
- `elapsed_minutes`: `number`
- `remaining_minutes`: `number`
- `total_duration_minutes`: `number`
- `extensions_used`: `number`
- `max_extensions`: `number`
- `can_extend`: `boolean`
- `is_time_up`: `boolean`
- `timestamp`: `string` (ISO 8601)

### `UserStatusResponse`

- `user_id`: `string`
- `workflow_state`: `string` (enum value)
- `timestamp`: `string` (ISO 8601)

### `TherapyStyleDTO`

- `style`: `string`
- `name`: `string`
- `description`: `string`

### `StatusMessageResponse`

- `message`: `string`
- `session_id`: `string | null`

## Endpoints

> **Deprecated routes removed**: `POST /api/user/profile` and `POST /api/therapy/plan` are retired; use the workflow step endpoints listed below instead.

### `GET /health`

- **200**: `HealthCheckResponse`

### `GET /api/user/profile?user_id=...&session_id=...`

- **200**: `UserProfileDTO`
- **400**: `{ "error": "User ID is required" }`
- **404**: `{ "error": "User profile not found" }` (or equivalent)

### `PUT /api/user/profile`

- Request: Full profile payload; omitted optional fields are set to `null`. Requires `session_id`.
- Status updates are rejected; workflow transitions are orchestrator-only.
- **200**: `UserProfileDTO`
- **400**: `{ "error": "<validation message>" }`
- **404**: `{ "error": "User profile not found" }`

### `PATCH /api/user/profile`

- Request: Partial profile payload; only provided fields are updated. Requires `session_id`.
- Status updates are rejected; workflow transitions are orchestrator-only.
- **200**: `UserProfileDTO`
- **400**: `{ "error": "<validation message>" }`
- **404**: `{ "error": "User profile not found" }`

### `GET /api/user/status?user_id=...`

- This user-level endpoint remains available after the active session closes.
- **200**: `UserStatusResponse`
- **400**: `{ "error": "User ID is required" }`
- **404**: `{ "error": "User not found: <id>" }` (or equivalent)

### `GET /api/user/profiles`

- **200**: `UserProfileListResponseDTO`

### `POST /api/user/register`

- Request: `CreateUserProfileRequestDTO`
- **201**: `UserRegisterResponseDTO`
- **400**: `{ "error": "<validation message>" }`

### `POST /api/user/login`

- Request: `UserLoginRequestDTO`
- **200**: `UserRegisterResponseDTO`
- **404**: `{ "error": "User profile not found" }`

### `GET /api/sessions?user_id=...&session_id=...`

- **200**: `SessionDTO[]`
- **400**: `{ "error": "User ID is required" }`

### `GET /api/sessions/<session_id>?user_id=...&session_id=...`

- **200**: `SessionDTO`
- **404**: `{ "error": "Session not found" }`

### `POST /api/sessions`

- Request: `{ "user_id": "..." }`
- **201**: `SessionDTO`
- **400**: `{ "error": "User ID is required" }`
- **404**: `{ "error": "User profile not found" }`

### `GET /api/therapy/plan?user_id=...&session_id=...`

- **200**: `TherapyPlanDTO` or `null` (returns `null` when no plan exists for the user)
- **400**: `{ "error": "User ID is required" }`

### `GET /api/therapy/styles?user_id=...&session_id=...`

- **200**: `TherapyStyleDTO[]`

### `GET /api/sessions/<session_id>/timer?user_id=...&session_id=...`

- **200**: `SessionTimerResponse`
- **404**: `{ "error": "<not found message>" }` (or equivalent)

### `POST /api/sessions/<session_id>/end`

- Request: `EndSessionRequestDTO`
- **200**: `EndSessionResponseDTO`
- Therapy closure returns `workflow_state = "plan_update_in_progress"` while
  reflection continues in the background. Poll `GET /api/user/status?user_id=...`
  to observe completion.

### `GET /api/version`

- **200**: `VersionInfoDTO`

### `POST /api/version/check`

- Request: `{ "client_version": "...", "client_type": "console" | "web" }`
- `web` remains an accepted wire-level discriminator for compatibility; it
  does not represent a maintained browser frontend.
- **200**: `VersionCheckResponseDTO`
- **400**: `{ "error": "Invalid request", "details": [...] }` (or other invalid request shapes)

### `GET /api/workflow/next`

- Query: `user_id`, `session_id` (required)
- **200**: `WorkflowNextActionDTO`
- **400**: `{ "error": "User ID is required" }`

### `POST /api/workflow/complete_profile`

- Request: `WorkflowCompleteProfileRequestDTO` (requires `session_id`)
- Session must be active for the user; WebSocket presence is optional.
- **200**: `WorkflowNextActionDTO`
- **400**: `{ "error": "<validation message>" }`

### `POST /api/workflow/select_therapy_style`

- Request: `WorkflowSelectTherapyStyleRequestDTO` (requires `session_id`)
- Session must be active for the user; WebSocket presence is optional.
- On success, the workflow moves from `assessment_complete` to `initial_plan_complete` and returns `required_action="start_therapy"`.
- **200**: `WorkflowNextActionDTO`
- **400**: `{ "error": "<validation message>" }`
- **404**: `{ "error": "User profile not found" }`

### `POST /api/workflow/start_therapy`

- Request: `{ "user_id": "...", "session_id": "..." }`
- Creates a new `session_type="therapy"` session linked to the selected plan while preserving the current WebSocket conversation flow.
- **201**: `{ "session": SessionDTO, "workflow_next_action": WorkflowNextActionDTO }`

### `POST /api/workflow/retry_plan_update`
- Body: `{ "user_id": string, "session_id": string }`
- Retries reflection persistence for the ended therapy session when the workflow is `plan_update_failed`.
- **202**: `WorkflowNextActionDTO`
