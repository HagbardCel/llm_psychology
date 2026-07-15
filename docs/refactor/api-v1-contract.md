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
| **StyleRecommendationSummary** | | | |
| `style_id` | string | yes | Recommended style identifier |
| `score` | float | yes | Normalized fit score in `[0, 1]` |
| `rationale` | string | yes | Short recommendation rationale |
| `key_topics` | list[string] | yes | Topics supporting the recommendation |
| **StyleOptionsResponse** | | | |
| `styles` | list[StyleSummary] | yes | Static style catalog |
| `recommendations` | list[StyleRecommendationSummary] | yes | Ranked recommendations from the latest completed assessment; empty before assessment completion |
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
| `client_message_id` | UUID \| null | no | Derived idempotency key from the owning chat turn on user and assistant messages (not stored on `messages`); `null` for system messages |
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
| `active_chat_turn` | ChatTurnSummary \| null | no | The currently pending durable chat turn, or `null` when no turn is pending. Completed and failed turns are resolved through durable session history and duplicate submission semantics |
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
- `GET /api/v1/state` is the canonical fresh-start read. An initialized database contains a seeded profile singleton; `GET /api/v1/profile` returns that seeded profile and any subsequently persisted partial or complete profile. Partial profiles persisted in `SETUP` remain readable. `404 not_found` is only a defensive response if the required profile singleton row is unexpectedly absent. The client fills or replaces the seeded profile through `PUT /api/v1/profile`.
- Once assessment completes, `GET /api/v1/styles` recommendations remain readable through `STYLE_SELECTION`, `READY`, `THERAPY`, and `POST_SESSION`.
- `GET /api/v1/health` reports **process readiness only**. Healthy means lifespan initialization and startup recovery completed, the application is accepting commands, and shutdown has not begun. The check does not call the LLM provider, mutate or probe SQLite per request, or claim provider health.

## 2. Endpoint matrix

| Method/path | Allowed stage | Request | Response | Errors | Revision effect |
|---|---|---|---|---|---|
| `GET /api/v1/state` | all | — | `200 AppSnapshot` | — | read only |
| `GET /api/v1/profile` | all | — | `200 ProfileResponse` | `404 not_found` if the required profile singleton row is unexpectedly absent | read only |
| `PUT /api/v1/profile` | `SETUP`, `INTAKE` | `ProfileUpdate` | `200 AppSnapshot` | `409 invalid_command`, `409 state_conflict`, `422 validation_error` | profile + revision |
| `GET /api/v1/styles` | all | — | `200 StyleOptionsResponse` | — | read only |
| `PUT /api/v1/style` | `STYLE_SELECTION` | `SelectStyle { expected_revision, style_id }` | `200 AppSnapshot` | `409 invalid_command`, `409 state_conflict`, `422 validation_error` | selected style + initial immutable plan + revision |
| `GET /api/v1/sessions` | all | — | `200 {sessions: list[SessionSummary]}` | — | read only |
| `GET /api/v1/sessions/{session_id}` | all | — | `200 SessionHistoryResponse` | `404 not_found` | read only |
| `POST /api/v1/sessions` | `READY` | `StartSession { expected_revision }` | `201 {session, snapshot}` | `409 invalid_command`, `409 state_conflict`, `409 busy` | new session + revision |
| `POST /api/v1/sessions/{session_id}/end` | `THERAPY` (active id) | `EndSession { expected_revision }` | `202 AppSnapshot` | `404 not_found`, `409 invalid_command`, `409 state_conflict`, `409 busy` | end session + post-session operation + revision |
| `POST /api/v1/operations/current/retry` | failed operation visible | `RetryOperation { expected_revision }` | `202 AppSnapshot` | `409 invalid_command`, `409 state_conflict`, `409 busy` | requeue same operation |
| `GET /api/v1/health` | all | — | `200 {status: "healthy"}` | `503` when process not ready | read only |
| `WS /api/v1/chat` | `INTAKE`, `THERAPY` for chat | see §3 | event stream | `error` events | chat acceptance increments revision; completion increments again |

State-changing HTTP requests require `expected_revision`. Non-chat commands are serialized through `expected_revision` and application invariants. A retry after an uncertain response fetches the authoritative snapshot (`GET /api/v1/state` or the conflict envelope's `current_snapshot`). Assessment and post-session work are idempotent through their operation keys. Chat uses the durable `(session_id, client_message_id)` key. V1 does not implement a generic HTTP idempotency-receipt subsystem.

`PUT /profile` transitions `SETUP` → `INTAKE` when the stored profile becomes complete. Intake completion is processor-driven and creates/reuses the assessment operation. The assessment operation persists formulation, style recommendations, and style-neutral initial plan material. `select_style` requires a completed assessment containing initial plan material; it performs no new LLM call and atomically stores the selected style and materializes the first immutable plan.

## 3. WebSocket messages

Application-owned generation publishes through
[`EventStream`](target-architecture.md#application-event-distribution); API adapters
translate to the wire union below. Disconnect unsubscribes one client only;
accepted generation continues.

Browser WebSocket handshakes containing an `Origin` header are accepted only when
that exact HTTP(S) Origin is present in `JUNG_API_ALLOWED_ORIGINS`. Native clients
without an `Origin` header remain accepted. The literal `Origin: null` value is
always rejected. This is browser cross-origin protection, not authentication. Use
complete HTTP(S) origins including the port where applicable; paths, WebSocket
URLs, and the string `null` are not valid trusted origins.

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
| `error` | `error`, optional `session_id`, optional `turn_id`, optional `client_message_id`, `request_id` | any time | failure recorded when applicable | see chat error table below |

Chat error revision semantics:

| Error point | Durable change | Revision |
|---|---|---|
| Before command acceptance | none | unchanged |
| After accepted generation fails | `ChatTurn → FAILED` | incremented |
| Ephemeral token delivery failure for one subscriber | none | unchanged |

A durable post-acceptance failure emits `snapshot_changed` after the turn is marked `FAILED`.

`error` correlation requirements:

| Error category | Required correlation fields |
|---|---|
| Command rejected before acceptance | current `request_id`; `session_id` and `client_message_id` when the command parsed successfully |
| Durable chat failure after acceptance | `session_id`, `turn_id`, `client_message_id`, and a transport `request_id` |
| Unrelated protocol or connection error | `request_id`; chat identifiers only when known |

Duplicate `(session_id, client_message_id)` retransmission of an existing `PENDING` or `COMPLETE` turn may produce **no new application event**. Clients must not rely on event replay for duplicate-success acknowledgement. When the same ID is retransmitted with different content, the original persisted user message remains authoritative.

Absence from `active_chat_turn` is not evidence that the durable turn row is absent. Completed and failed turns disappear from the snapshot; reconcile through session history and duplicate submission semantics.

Duplicate `(session_id, client_message_id)` resolution happens before revision validation. Precedence:

1. resolve duplicate durable state by `(session_id, client_message_id)`;
2. `PENDING` and `COMPLETE`: return durable state without revision validation;
3. permanent `FAILED`: return stored non-retryable error;
4. retryable `FAILED`: reject conflicting active generation as `busy` before structural checks;
5. retryable `FAILED` that is structurally obsolete (session closed, wrong stage, or a later durable message exists): return non-retryable stored-work error carrying the original failure code/message;
6. retryable `FAILED` that remains the latest conversational turn: validate `expected_revision`, then reset the same row to `PENDING` and schedule generation.

`busy` rejects a second distinct active generation.

## 4. Errors, revisions, and reconnect rules

### Error mapping

| Code | HTTP | Meaning |
|---|---|---|
| `invalid_command` | 409 | Command not permitted in current stage |
| `state_conflict` | 409 | Stale `expected_revision`; includes `current_snapshot` |
| `busy` | 409 | Conflicting session, mutation, operation, or generation |
| `not_found` | 404 | Unknown session or resource |
| `validation_error` | 422 | Request body failed validation |
| `llm_unavailable` | n/a — durable/WS | Provider was unavailable |
| `llm_timeout` | n/a — durable/WS | Provider request timed out |
| `invalid_llm_output` | n/a — durable/WS | Provider output failed validation |
| `operation_failed` | 409 | Durable operation already failed or cannot be accepted in current state |
| `internal_error` | 500 | Unexpected server failure |
| `not_ready` | 503 | API process not initialized or shutting down |

These codes primarily describe durable operation/chat failures and WebSocket error envelopes. V1 exposes no ordinary synchronous HTTP provider invocation. When an existing durable failure is surfaced as `StoredWorkFailure` through an HTTP command boundary, the response status is `409`; the stored public code, sanitized message, and retryability are preserved.

Stored public error messages on durable chat turns and operations are server-controlled and sanitized. Provider exception text remains in server logs only and is not persisted in `error_message`.

Durable internal failure codes that are not part of the public API vocabulary are exposed as `operation_failed`. Their sanitized message and retryability are preserved.

Malformed `X-Request-ID` request header values produce `422 validation_error` with a newly generated correlation ID in both the response header and error envelope. The malformed header value is never echoed.

Provider diagnostics remain in server logs only. LLM failure never advances workflow stage.

### Reconnect and uncertain delivery

After any disconnect or uncertain delivery, the client preserves the original `session_id`, `client_message_id`, and message content. Each transmission attempt uses a fresh `request_id` and the latest snapshot `expected_revision`.

One reconciliation invocation performs at most:

1. one initial authoritative HTTP refresh (`GET /state` and `GET /sessions/{session_id}` when needed);
2. zero or one retransmission of the same logical message;
3. one bounded wait for a matching `message_in_progress`, `message_completed`, or correlated `error`;
4. one final authoritative HTTP refresh;
5. return of a typed outcome to the caller.

A reconciliation call never loops or retransmits indefinitely. The caller decides whether to begin another explicit attempt. No generic retry of state-changing HTTP commands is allowed; chat retransmission is the narrow exception because it reuses the same durable `(session_id, client_message_id)` identity.

Canonical sequence:

1. establish `WS /api/v1/chat` (before authoritative reconciliation, or refresh again after connect);
2. `GET /api/v1/state`;
3. `GET /api/v1/sessions/{session_id}` when history is needed (for uncertain delivery, fetch the original command's `session_id`, even if that session is no longer active; a separate active-session read may be used for current UI rendering);
4. reconcile by `client_message_id`:
   - matching user and assistant with the same ID → complete;
   - matching user plus pending turn in snapshot → in progress;
   - matching user, no assistant, no pending turn → retransmit same ID;
   - no matching user message → retransmit same ID with latest revision;
5. when retransmitting, wait for matching `message_in_progress`, `message_completed`, or an error matching the current `request_id` before acceptance or the retained `client_message_id` after durable acceptance;
6. if no matching event within the bounded acknowledgement interval, fetch state and history again and treat refreshed durable HTTP state as authoritative;
7. never reconstruct a completed message from missed `token` events.

On reconnect the client resubscribes for live notifications only; there is no event replay buffer.
