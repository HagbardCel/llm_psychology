# API v1 Contract

> This document governs the supported `/api/v1` runtime contract.
>
> OpenAPI owns ordinary HTTP request/response DTO schemas, including
> `ChatRequest`, and documents the `200 application/x-ndjson` media type for
> chat. `api-v1.md` additionally owns the NDJSON stream framing, `ServerEvent`
> record vocabulary, event ordering, normal-completion vs disconnect terminal
> semantics, and retry rules.

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
| `POST /api/v1/chat` | `INTAKE`, `THERAPY` | `ChatRequest` | `200 application/x-ndjson` `ServerEvent` stream | pre-stream `422`/`503`; in-stream `error`/`message_failed` | user/assistant messages persist on accept/complete |

State-changing commands are serialized server-side and validated against
authoritative state at execution time; clients do not send concurrency tokens.
A retry after an uncertain response fetches the authoritative snapshot via
`GET /api/v1/state` and session history when needed. Assessment and post-session
work are idempotent through their operation keys. Chat uses the durable
`(session_id, client_message_id, role)` message key. V1 does not implement a
generic HTTP idempotency-receipt subsystem.

`PUT /profile` transitions `SETUP` → `INTAKE` when the stored profile becomes complete. Once `INTAKE` has begun, subsequent profile updates must keep the profile complete or the command returns `409 invalid_command`. Intake completion is processor-driven and creates/reuses the assessment operation. The assessment operation persists formulation, style recommendations, and style-neutral initial plan material. `select_style` requires a completed assessment containing initial plan material; it performs no new LLM call and atomically stores the selected style and materializes the first immutable plan.

## 3. Streaming chat

`POST /api/v1/chat` accepts one chat attempt and streams `ServerEvent` records as
NDJSON. The request owns generation through `TherapyApplication.stream_message`.
Client disconnect or cancellation cancels that attempt. There is no
multi-subscriber fan-out, no `snapshot_changed` / `operation_changed` stream,
and no event replay.

### Request

| Header / body | Value |
|---|---|
| Method / path | `POST /api/v1/chat` |
| `Content-Type` | `application/json` |
| `Accept` | `application/x-ndjson` |
| `X-Request-ID` | optional correlation UUID; server generates one when absent |
| Body | `ChatRequest` |

`ChatRequest` fields: `session_id`, `client_message_id`, `content`. The body has
no `type` field and no `request_id`. Correlation uses the `X-Request-ID`
request header. The typed client streams via
`JungApiClient.stream_message(...)`.

Browser CORS for ordinary HTTP remains governed by
`JUNG_API_ALLOWED_ORIGINS`. This document does not define a separate chat
handshake beyond standard HTTP CORS.

### Framing

The successful response is `200` with `Content-Type: application/x-ndjson`.
Each line is one JSON object (`ServerEvent`). The response `X-Request-ID`
header echoes the request correlation ID, and every event carries the same
`request_id`.

Where a stream event embeds a shared DTO such as `MessageResponse` or
`ErrorEnvelope`, use the same generated/shared schema (OpenAPI / contract
types) rather than duplicating nested fields here.

### Server events

| Event | Required identifiers | Ordering | Persistence point | Durable effect |
|---|---|---|---|---|
| `token` | `session_id`, `client_message_id`, `request_id`, `text` | after acceptance; ephemeral | none | none |
| `message_completed` | `session_id`, `client_message_id`, `request_id`, `user_message`, `assistant_message` | terminal | assistant message stored (or both already present) | completion persisted / idempotent reuse |
| `message_failed` | `session_id`, `client_message_id`, `request_id`, `error` (`ErrorEnvelope`) | terminal after acceptance | user message remains; no assistant | accepted chat attempt failed before durable assistant completion |
| `error` | `session_id`, `client_message_id`, `request_id`, `error` (`ErrorEnvelope`) | terminal (typically rejection or protocol failure after the stream has opened) | none unless noted | command/protocol rejection |

### Completion and disconnect

**Normal completion:** zero or more `token` events, then exactly one terminal
event (`message_completed`, `message_failed`, or `error`), then EOF.

**Disconnect / cancellation:** the HTTP stream may end without a terminal event.
The server does not fabricate a terminal event for client disconnect. Durable
outcome is uncertain to the client; recover through authoritative HTTP
state/history as for other uncertain delivery.

### Pre-stream HTTP errors vs in-stream `error`

Failures that occur before the NDJSON body begins are ordinary HTTP responses
(notably `422 validation_error`, `503 not_ready`). After the `200` NDJSON stream
has opened, rejections and failures are carried as in-stream `error` or
`message_failed` events. `ErrorEvent` always includes `session_id` and
`client_message_id` together with `request_id`.

Chat error durable semantics:

| Error point | Durable change |
|---|---|
| Pre-stream HTTP rejection | none |
| In-stream `error` before command acceptance | none |
| After an ordinary post-acceptance failure before completion (`message_failed`) | user message remains unanswered; no assistant row |
| Disconnect / cancel mid-generation | user message may remain unanswered on an open session |

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
and decide whether to issue a new `POST /api/v1/chat` with the same
`client_message_id` (retry) or a new ID. Each retry uses a fresh `request_id`.

## 4. Errors and reconnect rules

### Error mapping

| Code | HTTP | Meaning |
|---|---|---|
| `invalid_command` | 409 | Command not permitted in current stage or violates stage invariants (including incomplete profile during `INTAKE`, unanswered-message retry rules) |
| `busy` | 409 | Conflicting session, mutation, operation, or generation |
| `not_found` | 404 | Unknown session or resource |
| `validation_error` | 422 | Request body failed validation |
| `llm_unavailable` | n/a — stream / nested envelopes | Provider was unavailable |
| `llm_timeout` | n/a — stream / nested envelopes | Provider request timed out |
| `invalid_llm_output` | n/a — stream / nested envelopes | Provider output failed validation |
| `operation_failed` | n/a — stream / nested envelopes | Durable operation failure surfaced outside the HTTP command status map |
| `internal_error` | 500 | Unexpected server failure |
| `not_ready` | 503 | API process not initialized or shutting down |

`ErrorCode` still includes `llm_*` and `operation_failed` for stream
`message_failed` / nested envelopes. The HTTP status map for command exceptions
is the command subset only (`invalid_command`, `busy`, `not_found`,
`validation_error`, `internal_error`, `not_ready`). V1 exposes no ordinary
synchronous HTTP provider invocation outside the chat stream.

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
Each new chat attempt is a new `POST /api/v1/chat` stream; `request_id` should be
fresh per attempt. Clients do not carry or refresh a concurrency revision.

Canonical recovery steps (manual / console policy — not a built-in client
reconciler):

1. `GET /api/v1/state`;
2. `GET /api/v1/sessions/{session_id}` when history is needed;
3. decide from durable messages:
   - matching user and assistant with the same `client_message_id` → complete;
   - matching unanswered user on an open eligible session → issue a new
     `POST /api/v1/chat` and retransmit the same ID/content;
   - no matching user → send a new message (new or retained ID as appropriate);
4. never reconstruct a completed assistant message from missed `token` events.

Tokens are best-effort on the single streaming request; there is no replay
buffer.
