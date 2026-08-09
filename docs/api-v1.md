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
- `client_message_id` on `MessageResponse` is stored on the message row (required for `user` and `assistant`); durable uniqueness is `(session_id, client_message_id, role)`;
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
- `GET /api/v1/styles` always returns the style catalog. Recommendations are empty before assessment completion; afterward they contain the completed assessment recommendations and remain readable through `STYLE_SELECTION`, `READY`, `THERAPY`, and `POST_SESSION`;
- `GET /api/v1/health` reports **process readiness only** (`HealthResponse` with `status="healthy"`). Healthy means lifespan initialization and startup recovery completed, the application is accepting commands, and shutdown has not begun. The check does not call the LLM provider, mutate or probe SQLite per request, or claim provider health;
- For HTTP requests, the server generates `request_id` unless a supported correlation header is supplied;
- During `INTAKE`, `PUT /profile` may edit profile fields but the profile must remain complete; an incomplete body returns `409 invalid_command`;
- `AppSnapshotResponse` carries stage, completeness, active session, current operation, and available commands. It does not include an active chat turn or revision field. While generation is active, `available_commands` may be empty even though stage policy would otherwise allow commands.

## 2. Endpoint matrix

| Method/path | Allowed stage | Request | Response | Errors | Durable effect |
|---|---|---|---|---|---|
| `GET /api/v1/state` | all | — | `200 AppSnapshotResponse` | — | read only |
| `GET /api/v1/profile` | all | — | `200 ProfileResponse` | `404 not_found` if the required profile singleton row is unexpectedly absent | read only |
| `PUT /api/v1/profile` | `SETUP`, `INTAKE` | `ProfileUpdateRequest` | `200 AppSnapshotResponse` | `409 invalid_command`, `422 validation_error` | profile persisted; `SETUP` → `INTAKE` when complete |
| `GET /api/v1/styles` | all | — | `200 StyleOptionsResponse` | — | read only |
| `PUT /api/v1/style` | `STYLE_SELECTION` | `SelectStyleRequest` | `200 AppSnapshotResponse` | `409 invalid_command`, `422 validation_error` | selected style + initial immutable plan |
| `GET /api/v1/sessions` | all | — | `200 SessionListResponse` | — | read only |
| `GET /api/v1/sessions/{session_id}` | all | — | `200 SessionHistoryResponse` | `404 not_found` | read only |
| `POST /api/v1/sessions` | `READY` | — (bodyless) | `201 StartSessionResponse` | `409 invalid_command`, `409 busy` | new therapy session |
| `POST /api/v1/sessions/{session_id}/end` | `THERAPY` (active id) | — (bodyless) | `202 AppSnapshotResponse` | `404 not_found`, `409 invalid_command`, `409 busy` | end session + post-session operation |
| `POST /api/v1/operations/current/retry` | failed operation visible | — (bodyless) | `202 AppSnapshotResponse` | `409 invalid_command`, `409 busy` | requeue same operation |
| `GET /api/v1/health` | all | — | `200 HealthResponse` (`status="healthy"`) | `503` when process not ready | read only |
| `WS /api/v1/chat` | `INTAKE`, `THERAPY` for chat | see §3 | one-shot event stream | `error` / `message_failed` | user/assistant messages persist on accept/complete |

State-changing commands are serialized server-side and validated against
authoritative state at execution time; clients do not send concurrency tokens.
A retry after an uncertain response fetches the authoritative snapshot via
`GET /api/v1/state` and session history when needed. Assessment and post-session
work are idempotent through their operation keys. Chat uses the durable
`(session_id, client_message_id, role)` message key. V1 does not implement a
generic HTTP idempotency-receipt subsystem.

`PUT /profile` transitions `SETUP` → `INTAKE` when the stored profile becomes complete. Once `INTAKE` has begun, subsequent profile updates must keep the profile complete or the command returns `409 invalid_command`. Intake completion is processor-driven and creates/reuses the assessment operation. The assessment operation persists formulation, style recommendations, and style-neutral initial plan material. `select_style` requires a completed assessment containing initial plan material; it performs no new LLM call and atomically stores the selected style and materializes the first immutable plan.

## 3. WebSocket messages

`WS /api/v1/chat` is a **one-shot** connection: accept handshake → receive exactly
one `send_message` frame → stream zero or more `token` events → emit one
terminal event (`message_completed`, `message_failed`, or `error`) → close.
The connection owns generation through `TherapyApplication.stream_message`.
Disconnect cancels that attempt. There is no multi-subscriber fan-out, no
`snapshot_changed` / `operation_changed` stream, and no event replay.

Normally, a valid one-shot chat connection emits one terminal event and closes.
If an additional inbound data frame arrives while the first valid command is
active, the server aborts that connection: it cancels/drains owned generation and
closes without emitting a terminal event for the active request. Its durable
outcome is therefore uncertain to the client; recover through authoritative HTTP
state/history as for other uncertain delivery. Initial-frame validation failures
still emit `error`.

Browser WebSocket handshakes containing an `Origin` header are accepted only when
that exact HTTP(S) Origin is present in `JUNG_API_ALLOWED_ORIGINS`. Native clients
without an `Origin` header remain accepted. The literal `Origin: null` value is
always rejected. This is browser cross-origin protection, not authentication. Use
complete HTTP(S) origins including the port where applicable; paths, WebSocket
URLs, and the string `null` are not valid trusted origins.

Where a WebSocket event embeds a shared DTO such as `MessageResponse` or
`ErrorEnvelope`, use the same generated/shared schema (OpenAPI / contract
types) rather than duplicating nested fields here.

### Client

| Type | Body | Semantics |
|---|---|---|
| `send_message` | `SendMessageCommand` | Accept or retry a chat message for the active intake or therapy session |

`SendMessageCommand` fields: `type`, `session_id`, `client_message_id`,
`request_id`, `content`. The typed client builds these via
`JungApiClient.new_message_command(session_id, content, ...)`.

### Server

| Event | Required identifiers | Ordering | Persistence point | Durable effect |
|---|---|---|---|---|
| `token` | `session_id`, `client_message_id`, `request_id`, `text` | after acceptance; ephemeral | none | none |
| `message_completed` | `session_id`, `client_message_id`, `request_id`, `user_message`, `assistant_message` | terminal | assistant message stored (or both already present) | completion persisted / idempotent reuse |
| `message_failed` | `session_id`, `client_message_id`, `request_id`, `error` (`ErrorEnvelope`) | terminal after acceptance | user message remains; no assistant | accepted chat attempt failed before durable assistant completion |
| `error` | `error` (`ErrorEnvelope`), `request_id`; optional `session_id`, optional `client_message_id` | terminal (typically pre-acceptance or protocol) | none unless noted | command/protocol rejection |

Chat error durable semantics:

| Error point | Durable change |
|---|---|
| Before command acceptance (`error`) | none |
| After an ordinary post-acceptance failure before completion (`message_failed`) | user message remains unanswered; no assistant row |
| Disconnect / cancel mid-generation | user message may remain unanswered on an open session |

`error` correlation fields:

| Error category | Required / optional identifiers |
|---|---|
| Command rejected before acceptance | `request_id`; `session_id` and `client_message_id` when the command parsed successfully |
| Protocol / validation failure | `request_id`; chat identifiers only when known |
| Unrelated connection error | `request_id`; chat identifiers only when known |

Duplicate `(session_id, client_message_id)` resolution (message-native):

1. matching user **and** assistant with the same content → `message_completed` with durable pair;
2. same ID, different content → `invalid_command` via `error`;
3. unanswered user only, structurally eligible → regenerate (retry);
4. unanswered user only, not eligible (closed session, wrong stage, not latest) → `invalid_command` via `error`;
5. open session already ends with a different unanswered user → `invalid_command` (must retry that ID first);
6. conflicting active generation → `busy` via `error`.

There is **no** client reconciliation protocol, acknowledgement timeout, or
event-wait loop in the supported client. After uncertain delivery, refresh
authoritative HTTP state (`GET /state`, `GET /sessions/{session_id}` as needed)
and decide whether to open a new one-shot WebSocket with the same
`client_message_id` (retry) or a new ID.

## 4. Errors and reconnect rules

### Error mapping

| Code | HTTP | Meaning |
|---|---|---|
| `invalid_command` | 409 | Command not permitted in current stage or violates stage invariants (including incomplete profile during `INTAKE`, unanswered-message retry rules) |
| `busy` | 409 | Conflicting session, mutation, operation, or generation |
| `not_found` | 404 | Unknown session or resource |
| `validation_error` | 422 | Request body failed validation |
| `llm_unavailable` | n/a — WS / nested envelopes | Provider was unavailable |
| `llm_timeout` | n/a — WS / nested envelopes | Provider request timed out |
| `invalid_llm_output` | n/a — WS / nested envelopes | Provider output failed validation |
| `operation_failed` | n/a — WS / nested envelopes | Durable operation failure surfaced outside the HTTP command status map |
| `internal_error` | 500 | Unexpected server failure |
| `not_ready` | 503 | API process not initialized or shutting down |

`ErrorCode` still includes `llm_*` and `operation_failed` for WebSocket
`message_failed` / nested envelopes. The HTTP status map for command exceptions
is the command subset only (`invalid_command`, `busy`, `not_found`,
`validation_error`, `internal_error`, `not_ready`). V1 exposes no ordinary
synchronous HTTP provider invocation.

Public error messages are server-controlled and sanitized. Provider details are
not exposed through API responses or public durable operation error fields.
Server-side ordinary logs contain bounded/sanitized operational diagnostics;
opt-in `JUNG_DEBUG_RUN_DIR` traces may contain sensitive provider traffic,
including exact prompts or responses. See
[Safety and Data Handling](safety-and-data.md).

Durable internal failure codes that are not part of the public API vocabulary
are exposed as `operation_failed` (or classified LLM codes where applicable).
Their sanitized message and retryability are preserved on operation rows.

Malformed `X-Request-ID` request header values produce `422 validation_error`
with a newly generated correlation ID in both the response header and error
envelope. The malformed header value is never echoed.

LLM failure never advances workflow stage.

### After disconnect or uncertain delivery

After any disconnect or uncertain delivery, the client preserves the original
`session_id`, `client_message_id`, and message content when a retry is intended.
Each new WebSocket attempt uses a fresh connection; `request_id` should be
fresh per attempt. Clients do not carry or refresh a concurrency revision.

Canonical recovery steps (manual / console policy — not a built-in client
reconciler):

1. `GET /api/v1/state`;
2. `GET /api/v1/sessions/{session_id}` when history is needed;
3. decide from durable messages:
   - matching user and assistant with the same `client_message_id` → complete;
   - matching unanswered user on an open eligible session → open a new one-shot
     `WS /api/v1/chat` and retransmit the same ID/content;
   - no matching user → send a new message (new or retained ID as appropriate);
4. never reconstruct a completed assistant message from missed `token` events.

Tokens are best-effort on the single streaming connection; there is no replay
buffer.
