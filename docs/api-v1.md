---
owner: engineering
status: active
last_reviewed: 2026-08-08
review_cycle_days: 30
source_of_truth_for: Supported /api/v1 HTTP semantics and WebSocket wire contract
---

# API v1 Contract

> This document governs the supported `/api/v1` runtime contract.
>
> OpenAPI (`/api/v1/openapi.json`) owns the mechanically generated HTTP
> request/response schema. Swagger UI and ReDoc are disabled. This document owns
> HTTP semantics and the complete WebSocket wire contract and semantics.

All routes are rooted at `/api/v1`. No endpoint accepts `user_id`. There is no generic workflow mutation route.

## 1. HTTP semantics

Mechanical HTTP DTO field inventories live in the generated OpenAPI schema.
This section records contract semantics that OpenAPI alone does not adequately
express.

Policy decisions:

- session listing is non-paginated and ordered by `started_at` descending;
- `PUT /profile` is allowed only in `SETUP` and `INTAKE`;
- `PUT /style` is allowed only in `STYLE_SELECTION` and is immutable thereafter;
- most state-changing HTTP endpoints return `AppSnapshotResponse`; `POST /sessions` returns `StartSessionResponse`;
- `ProfileResponse.current_plan` exposes the active plan revision; no separate current-plan endpoint is required for v1 clients;
- `PlanSummaryResponse` is the session-history list view; `PlanDetailResponse` is the full immutable revision returned on profile read;
- `GET /api/v1/sessions` returns `SessionListResponse`; `GET /api/v1/sessions/{session_id}` returns `SessionHistoryResponse` with messages, linked plans, and closed-session artifacts when available;
- `PlanDetailResponse.current_progress` is a required non-empty string on every revision; the initial immutable plan uses assessment-derived progress text;
- `PlanDetailResponse.session_briefing` is an opaque server-validated JSON document; clients do not interpret its internal shape in v1. When present, the briefing may include `intervention_evidence` items with the observable shape below;
- `SessionDetailResponse.briefing` is the canonical session-scoped artifact on the closed source session; `PlanDetailResponse.session_briefing` is an immutable snapshot copied from the source session at plan-revision creation when a briefing exists; clients needing the source artifact use `GET /sessions/{source_session_id}`;
- `client_message_id` on `MessageResponse` is a derived read-model field joined from the owning chat turn on user and assistant messages (not stored on `messages`); it is `null` for system messages;
- Observable `intervention_evidence` item fields (when present inside a briefing document):
  - `intervention_description` (string): model-generated interpretive label
  - `therapist_sequence` (int): transcript sequence of the cited therapist turn
  - `therapist_content` (string): server-resolved full whitespace-normalized content of that assistant turn
  - `patient_sequence` (int \| null): later patient turn when a response is cited
  - `patient_content` (string \| null): server-resolved full whitespace-normalized content of that user turn
  - `status` (`"delivered"` \| `"response_cited"`): derived by the server from whether a later patient turn citation is present; never model-controlled. `response_cited` means a later user turn was cited, not that the turn was proven to be a semantic response;
- Intervention evidence statuses are `"delivered"` and `"response_cited"` only;
- Durable derived-profile records are not part of `ProfileResponse` and are not public API data in v1;
- `ProfileWire` is the user-editable identity and preferences record; intake evidence, assessment formulation, and derived therapeutic profile data are separate backend-owned validated documents and cannot be overwritten through `PUT /profile`;
- v1 does not implement a generic HTTP `Idempotency-Key` header or command-receipt store;
- `GET /api/v1/state` is the canonical fresh-start read. An initialized database contains a seeded profile singleton; `GET /api/v1/profile` returns that seeded profile and any subsequently persisted partial or complete profile. Partial profiles persisted in `SETUP` remain readable. `404 not_found` is only a defensive response if the required profile singleton row is unexpectedly absent. The client fills or replaces the seeded profile through `PUT /api/v1/profile`;
- Once assessment completes, `GET /api/v1/styles` recommendations remain readable through `STYLE_SELECTION`, `READY`, `THERAPY`, and `POST_SESSION`;
- `GET /api/v1/health` reports **process readiness only** (`HealthResponse` with `status="healthy"`). Healthy means lifespan initialization and startup recovery completed, the application is accepting commands, and shutdown has not begun. The check does not call the LLM provider, mutate or probe SQLite per request, or claim provider health;
- For HTTP requests, the server generates `request_id` unless a supported correlation header is supplied;
- `state_conflict` responses include `current_snapshot` with the authoritative revision.

## 2. Endpoint matrix

| Method/path | Allowed stage | Request | Response | Errors | Revision effect |
|---|---|---|---|---|---|
| `GET /api/v1/state` | all | — | `200 AppSnapshotResponse` | — | read only |
| `GET /api/v1/profile` | all | — | `200 ProfileResponse` | `404 not_found` if the required profile singleton row is unexpectedly absent | read only |
| `PUT /api/v1/profile` | `SETUP`, `INTAKE` | `ProfileUpdateRequest` | `200 AppSnapshotResponse` | `409 invalid_command`, `409 state_conflict`, `422 validation_error` | profile + revision |
| `GET /api/v1/styles` | all | — | `200 StyleOptionsResponse` | — | read only |
| `PUT /api/v1/style` | `STYLE_SELECTION` | `SelectStyleRequest` | `200 AppSnapshotResponse` | `409 invalid_command`, `409 state_conflict`, `422 validation_error` | selected style + initial immutable plan + revision |
| `GET /api/v1/sessions` | all | — | `200 SessionListResponse` | — | read only |
| `GET /api/v1/sessions/{session_id}` | all | — | `200 SessionHistoryResponse` | `404 not_found` | read only |
| `POST /api/v1/sessions` | `READY` | `StartSessionRequest` | `201 StartSessionResponse` | `409 invalid_command`, `409 state_conflict`, `409 busy` | new session + revision |
| `POST /api/v1/sessions/{session_id}/end` | `THERAPY` (active id) | `EndSessionRequest` | `202 AppSnapshotResponse` | `404 not_found`, `409 invalid_command`, `409 state_conflict`, `409 busy` | end session + post-session operation + revision |
| `POST /api/v1/operations/current/retry` | failed operation visible | `RetryOperationRequest` | `202 AppSnapshotResponse` | `409 invalid_command`, `409 state_conflict`, `409 busy` | requeue same operation |
| `GET /api/v1/health` | all | — | `200 HealthResponse` (`status="healthy"`) | `503` when process not ready | read only |
| `WS /api/v1/chat` | `INTAKE`, `THERAPY` for chat | see §3 | event stream | `error` events | chat acceptance increments revision; completion increments again |

State-changing HTTP requests require `expected_revision`. Non-chat commands are serialized through `expected_revision` and application invariants. A retry after an uncertain response fetches the authoritative snapshot (`GET /api/v1/state` or the conflict envelope's `current_snapshot`). Assessment and post-session work are idempotent through their operation keys. Chat uses the durable `(session_id, client_message_id)` key. V1 does not implement a generic HTTP idempotency-receipt subsystem.

`PUT /profile` transitions `SETUP` → `INTAKE` when the stored profile becomes complete. Intake completion is processor-driven and creates/reuses the assessment operation. The assessment operation persists formulation, style recommendations, and style-neutral initial plan material. `select_style` requires a completed assessment containing initial plan material; it performs no new LLM call and atomically stores the selected style and materializes the first immutable plan.

## 3. WebSocket messages

Application-owned generation publishes through the in-process event stream
described in [Architecture](architecture.md#application-event-distribution);
API adapters translate to the wire union below. Disconnect unsubscribes one
client only; accepted generation continues.

Browser WebSocket handshakes containing an `Origin` header are accepted only when
that exact HTTP(S) Origin is present in `JUNG_API_ALLOWED_ORIGINS`. Native clients
without an `Origin` header remain accepted. The literal `Origin: null` value is
always rejected. This is browser cross-origin protection, not authentication. Use
complete HTTP(S) origins including the port where applicable; paths, WebSocket
URLs, and the string `null` are not valid trusted origins.

Where a WebSocket event embeds a shared DTO such as `ChatTurnSummaryResponse`,
`MessageResponse`, `AppSnapshotResponse`, `OperationSummaryResponse`, or
`ErrorEnvelope`, use the same generated/shared schema (OpenAPI / contract
types) rather than duplicating nested fields here.

### Client

| Type | Body | Semantics |
|---|---|---|
| `send_message` | `SendMessageCommand` | Accept a chat turn for the active intake or therapy session |

### Server

| Event | Required identifiers | Ordering | Persistence point | Revision |
|---|---|---|---|---|
| `token` | `session_id`, `turn_id`, `request_id`, `sequence`, `text` | strictly increasing `sequence` per turn | none (ephemeral) | none |
| `message_in_progress` | `session_id`, `turn` (`ChatTurnSummaryResponse`) | after acceptance | user message + pending turn stored | incremented at acceptance |
| `message_completed` | `session_id`, `turn` (`ChatTurnSummaryResponse`), `message` (`MessageResponse`) | after final token | assistant message + complete turn stored | incremented at completion |
| `snapshot_changed` | `snapshot` (`AppSnapshotResponse`) | after durable mutation | snapshot reread | matches stored revision |
| `operation_changed` | `operation` (`OperationSummaryResponse`), `snapshot` (`AppSnapshotResponse`) | when operation status changes | operation row updated | matches stored revision |
| `error` | `error` (`ErrorEnvelope`), optional `session_id`, optional `turn_id`, optional `client_message_id`, `request_id` | any time | failure recorded when applicable | see chat error table below |

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

Stored public error messages on durable chat turns and operations are server-controlled and sanitized. Provider details are not exposed through API responses or public durable error fields. Server-side ordinary logs contain bounded/sanitized operational diagnostics; opt-in `JUNG_DEBUG_RUN_DIR` traces may contain sensitive provider traffic, including exact prompts or responses. See [Safety and Data Handling](safety-and-data.md).

Durable internal failure codes that are not part of the public API vocabulary are exposed as `operation_failed`. Their sanitized message and retryability are preserved.

Malformed `X-Request-ID` request header values produce `422 validation_error` with a newly generated correlation ID in both the response header and error envelope. The malformed header value is never echoed.

LLM failure never advances workflow stage.

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
