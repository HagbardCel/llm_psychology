---
owner: engineering
status: accepted
last_reviewed: 2026-07-11
review_cycle_days: 30
source_of_truth_for: Target /api/v1 external semantics
---

# Target API v1 Contract

> This is the cutover contract, not the legacy API. Until cutover, the current contracts in `docs/contracts/` and `docs/WEBSOCKET_PROTOCOL.md` govern runtime behavior.

All routes are rooted at `/api/v1`. No endpoint accepts `user_id`. There is no generic workflow mutation route.

## 1. Shared schemas

| Field | Type | Required | Meaning |
|---|---|---|---|
| **Profile** | | | |
| `name` | string | yes | Display name |
| `primary_language` | string | yes | Preferred conversation language |
| `date_of_birth` | date \| null | no | Optional demographic field |
| `notes` | string \| null | no | Free-form profile notes |
| **ProfileUpdate** | | | |
| `expected_revision` | int | yes | Optimistic concurrency token |
| `profile` | Profile | yes | Replacement profile payload |
| **StyleSummary** | | | |
| `id` | string | yes | Stable style identifier |
| `name` | string | yes | Human-readable label |
| `description` | string | yes | Short style summary |
| **SessionSummary** | | | |
| `id` | UUID | yes | Session identifier |
| `kind` | `"intake"` \| `"therapy"` | yes | Session type; do not infer from `plan_id` alone |
| `started_at` | datetime | yes | Session start timestamp |
| `ended_at` | datetime \| null | no | End timestamp when closed |
| `plan_id` | UUID \| null | no | Plan revision effective at session start |
| **SessionDetail** | | | |
| (all `SessionSummary` fields) | | | |
| `summary` | string \| null | no | Post-session reflection summary when closed |
| `briefing` | opaque JSON \| null | no | Session-scoped briefing artifact when present |
| **Message** | | | |
| `id` | UUID | yes | Message identifier |
| `session_id` | UUID | yes | Owning session |
| `sequence` | int | yes | Monotonic order within session |
| `role` | `"user"` \| `"assistant"` \| `"system"` | yes | Speaker role |
| `content` | string | yes | Message body |
| `created_at` | datetime | yes | Persistence timestamp |
| `client_message_id` | UUID \| null | no | Idempotency key for user turns |
| **PlanSummary** | | | |
| `id` | UUID | yes | Immutable plan revision identifier |
| `version` | int | yes | Monotonic plan version |
| `source_session_id` | UUID \| null | no | Session that produced the revision |
| `supersedes_plan_id` | UUID \| null | no | Previous revision link |
| `created_at` | datetime | yes | Creation timestamp |
| **PlanDetail** | | | |
| `id` | UUID | yes | Immutable plan revision identifier |
| `version` | int | yes | Monotonic plan version |
| `selected_style` | string | yes | Selected therapy style |
| `focus` | string | yes | Current therapeutic focus |
| `themes` | list[string] | yes | Themes tracked by the plan |
| `goals` | list[string] | yes | Therapeutic goals |
| `current_progress` | string | yes | Qualitative progress assessment |
| `planned_interventions` | list[string] | yes | Planned interventions or directions |
| `revision_recommendations` | list[string] | yes | Recommendations from the latest revision |
| `session_briefing` | opaque validated JSON \| null | no | Server-validated resumption briefing; client display-only in v1 |
| `source_session_id` | UUID \| null | no | Session that produced the revision |
| `supersedes_plan_id` | UUID \| null | no | Previous revision link |
| `created_at` | datetime | yes | Creation timestamp |
| **OperationSummary** | | | |
| `id` | UUID | yes | Operation identifier |
| `kind` | `"assessment"` \| `"post_session"` | yes | Operation type |
| `status` | `"pending"` \| `"running"` \| `"complete"` \| `"failed"` | yes | Durable operation status |
| `source_session_id` | UUID \| null | no | Source session for the operation |
| `error` | ErrorEnvelope \| null | no | Last failure when `failed` |
| **ChatTurnSummary** | | | |
| `id` | UUID | yes | Turn identifier |
| `session_id` | UUID | yes | Active chat session |
| `client_message_id` | UUID | yes | Client idempotency key |
| `status` | `"pending"` \| `"complete"` \| `"failed"` | yes | Turn lifecycle status |
| `user_message_id` | UUID | yes | Persisted user message |
| `assistant_message_id` | UUID \| null | no | Persisted assistant message when complete |
| `error` | ErrorEnvelope \| null | no | Failure details when `failed` |
| **AppSnapshot** | | | |
| `revision` | int | yes | Monotonic snapshot revision |
| `stage` | Stage | yes | Current workflow stage |
| `profile_complete` | bool | yes | Whether profile satisfies completeness policy |
| `selected_style` | string \| null | no | Selected therapy style |
| `active_session` | SessionSummary \| null | no | Current open session |
| `operation` | OperationSummary \| null | no | Current background operation |
| `active_chat_turn` | ChatTurnSummary \| null | no | In-flight or last accepted chat turn |
| `available_commands` | list[Command] | yes | Backend-derived permitted commands |
| **ProfileResponse** | | | |
| `profile` | Profile | yes | Current profile |
| `current_plan` | PlanDetail \| null | no | Active plan revision referenced by profile lifecycle |
| `snapshot` | AppSnapshot | yes | Authoritative snapshot |
| **SessionHistoryResponse** | | | |
| `session` | SessionDetail | yes | Requested session with closed-session artifacts when available |
| `messages` | list[Message] | yes | Ordered durable messages |
| `plans` | list[PlanSummary] | yes | Plan revisions linked to the session |
| **ErrorResponse / ErrorEnvelope** | | | |
| `code` | error code literal | yes | Stable machine-readable code |
| `message` | string | yes | Human-readable summary |
| `request_id` | UUID | yes | Correlation identifier |
| `current_snapshot` | AppSnapshot \| null | no | Present for `state_conflict` |
| `retryable` | bool | no | Whether the client may retry |

For HTTP requests, the server generates `request_id` unless a supported correlation header is supplied.

Policy decisions:

- session listing is non-paginated and ordered by `started_at` descending;
- `PUT /profile` is allowed only in `SETUP` and `INTAKE`;
- `PUT /style` is allowed only in `STYLE_SELECTION` and is immutable thereafter;
- most mutations return `AppSnapshot`; exceptions are `GET /profile` → `ProfileResponse` and `POST /sessions` → `{session, snapshot}`.
- `ProfileResponse.current_plan` exposes the active plan revision; no separate current-plan endpoint is required for Phase 1 clients.
- `PlanSummary` is the session-history list view; `PlanDetail` is the full immutable revision returned on profile read.
- `GET /api/v1/sessions` returns `SessionSummary` rows; `GET /api/v1/sessions/{session_id}` returns `SessionDetail` with messages, linked plans, and closed-session artifacts when available.
- `PlanDetail.current_progress` is a required non-empty string on every revision; the initial immutable plan uses assessment-derived progress text.
- `PlanDetail.session_briefing` is an opaque server-validated JSON document; clients do not interpret its internal shape in v1.
- `SessionDetail.briefing` is the canonical session-scoped artifact on the closed source session; `PlanDetail.session_briefing` is an immutable snapshot copied from the source session at plan-revision creation when a briefing exists; clients needing the source artifact use `GET /sessions/{source_session_id}`.
- API `Profile` is the user-editable identity and preferences record; intake evidence, assessment formulation, and derived therapeutic profile data are separate backend-owned validated documents and cannot be overwritten through `PUT /profile`.
- v1 does not implement a generic HTTP `Idempotency-Key` header or command-receipt store.

## 2. Endpoint matrix

| Method/path | Allowed stage | Request | Response | Errors | Revision effect |
|---|---|---|---|---|---|
| `GET /api/v1/state` | all | — | `200 AppSnapshot` | — | read only |
| `GET /api/v1/profile` | all | — | `200 ProfileResponse` | — | read only |
| `PUT /api/v1/profile` | `SETUP`, `INTAKE` | `ProfileUpdate` | `200 AppSnapshot` | `409 invalid_command`, `409 state_conflict`, `422 validation_error` | profile + revision |
| `GET /api/v1/styles` | all | — | `200 {styles: list[StyleSummary]}` | — | read only |
| `PUT /api/v1/style` | `STYLE_SELECTION` | `SelectStyle { expected_revision, style_id }` | `200 AppSnapshot` | `409 invalid_command`, `409 state_conflict`, `422 validation_error` | selected style + initial immutable plan + revision |
| `GET /api/v1/sessions` | all | — | `200 {sessions: list[SessionSummary]}` | — | read only |
| `GET /api/v1/sessions/{session_id}` | all | — | `200 SessionHistoryResponse` | `404 not_found` | read only |
| `POST /api/v1/sessions` | `READY` | `StartSession { expected_revision }` | `201 {session, snapshot}` | `409 invalid_command`, `409 state_conflict`, `409 busy` | new session + revision |
| `POST /api/v1/sessions/{session_id}/end` | `THERAPY` (active id) | `EndSession { expected_revision }` | `202 AppSnapshot` | `404 not_found`, `409 invalid_command`, `409 state_conflict`, `409 busy` | end session + post-session operation + revision |
| `POST /api/v1/operations/current/retry` | failed operation visible | `RetryOperation { expected_revision }` | `202 AppSnapshot` | `409 invalid_command`, `409 state_conflict`, `409 busy` | requeue same operation |
| `GET /api/v1/health` | all | — | `200 {status: "healthy"}` | `503` when unavailable | read only |
| `WS /api/v1/chat` | `INTAKE`, `THERAPY` for chat | see §3 | event stream | `error` events | chat acceptance increments revision; completion increments again |

State-changing HTTP requests require `expected_revision`. Non-chat commands are serialized through `expected_revision` and application invariants. A retry after an uncertain response fetches the authoritative snapshot (`GET /api/v1/state` or the conflict envelope's `current_snapshot`). Assessment and post-session work are idempotent through their operation keys. Chat uses the durable `(session_id, client_message_id)` key. V1 does not implement a generic HTTP idempotency-receipt subsystem.

`PUT /profile` transitions `SETUP` → `INTAKE` when the stored profile becomes complete. Intake completion is processor-driven and creates/reuses the assessment operation. The assessment operation persists formulation, style recommendations, and style-neutral initial plan material. `select_style` requires a completed assessment containing initial plan material; it performs no new LLM call and atomically stores the selected style and materializes the first immutable plan.

## 3. WebSocket messages

Application-owned generation publishes through
[`EventStream`](target-architecture.md#application-event-distribution); API adapters
translate to the wire union below. Disconnect unsubscribes one client only;
accepted generation continues.

### Client

| Message | Fields | Semantics |
|---|---|---|
| `send_message` | `type`, `session_id`, `client_message_id`, `request_id`, `expected_revision`, `content` | Accept a chat turn for the active intake or therapy session |

### Server

| Event | Required identifiers | Ordering | Persistence point | Revision |
|---|---|---|---|---|
| `token` | `session_id`, `turn_id`, `request_id`, `sequence`, `text` | strictly increasing `sequence` per turn | none (ephemeral) | none |
| `message_in_progress` | `session_id`, `turn` | after acceptance | user message + pending turn stored | incremented at acceptance |
| `message_completed` | `session_id`, `turn`, `message` | after final token | assistant message + complete turn stored | incremented at completion |
| `snapshot_changed` | `snapshot` | after durable mutation | snapshot reread | matches stored revision |
| `operation_changed` | `operation`, `snapshot` | when operation status changes | operation row updated | matches stored revision |
| `error` | `error`, optional `session_id`, `request_id` | any time | failure recorded when applicable | see chat error table below |

Chat error revision semantics:

| Error point | Durable change | Revision |
|---|---|---|
| Before command acceptance | none | unchanged |
| After accepted generation fails | `ChatTurn → FAILED` | incremented |
| Ephemeral token delivery failure for one subscriber | none | unchanged |

A durable post-acceptance failure emits `snapshot_changed` after the turn is marked `FAILED`.

Duplicate `(session_id, client_message_id)` resolution happens before revision validation: pending → `message_in_progress`; complete → persisted completion; retryable failed → reuse turn; permanent failed → stored error. `busy` rejects a second distinct active generation.

## 4. Errors, revisions, and reconnect rules

### Error mapping

| Code | HTTP | Meaning |
|---|---|---|
| `invalid_command` | 409 | Command not permitted in current stage |
| `state_conflict` | 409 | Stale `expected_revision`; includes `current_snapshot` |
| `busy` | 409 | Conflicting session, mutation, operation, or generation |
| `not_found` | 404 | Unknown session or resource |
| `validation_error` | 422 | Request body failed validation |
| `llm_unavailable` | 503 | Provider unreachable |
| `llm_timeout` | 504 | Provider timeout |
| `invalid_llm_output` | 422 | Structured output parse/validation failure |
| `operation_failed` | 409 | Durable operation already failed or cannot be accepted in current state |
| `internal_error` | 500 | Unexpected server failure |

Genuine bad upstream protocol responses may map to `502` via `internal_error` or a future provider-specific code; do not overload `llm_unavailable`.

Provider diagnostics remain in server logs only. LLM failure never advances workflow stage.

### Reconnect rules

Canonical client sequence after any disconnect:

1. `GET /api/v1/state`
2. `GET /api/v1/sessions/{active_session_id}` when history is needed
3. establish `WS /api/v1/chat`
4. treat persisted HTTP state and stored messages as authoritative
5. never reconstruct a completed message from missed `token` events

On reconnect the client resubscribes for live notifications only; there is no event replay buffer.
