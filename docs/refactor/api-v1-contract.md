---
owner: engineering
status: proposed
last_reviewed: 2026-07-11
review_cycle_days: 30
source_of_truth_for: Target /api/v1 external semantics
---

# Target API v1 Contract

> Target specification only. The current HTTP and WebSocket contracts remain active until Phase 6.

## Transport

HTTP provides `GET /state`, `/profile`, `/styles`, `/sessions`, `/sessions/{id}`, `/health`; `PUT /profile`, `/style`; `POST /sessions`, `/sessions/{id}/end`, and `/operations/current/retry`. All routes are rooted at `/api/v1`; none accept `user_id`.

`WS /api/v1/chat` accepts only `send_message`. A command has `session_id`, `client_message_id`, `request_id`, `expected_revision`, and content. Non-chat mutations use HTTP and require `expected_revision`.

## Snapshot and events

`AppSnapshot` contains revision, stage, profile completion, selected style, active session, current workflow operation, active chat turn, and available commands. Notifications are hints; HTTP state/history is authoritative after reconnect.

Server events are discriminated unions: `token`, `message_in_progress`, `message_completed`, `snapshot_changed`, `operation_changed`, and `error`. Every chat event contains session and request identifiers. Tokens are ephemeral, ordered per request, not replayed, and never alter revision.

For accepted chat: persist user message/pending turn and revision N+1; emit snapshot; stream tokens; persist assistant message/complete turn and N+2; emit completion then snapshot. Completion and snapshot notifications go to all local observers of the active session.

## Errors and idempotency

Stable errors are `invalid_command`, `state_conflict`, `busy`, `not_found`, `llm_unavailable`, `llm_timeout`, `invalid_llm_output`, `operation_failed`, and `internal_error`.

Duplicate client message IDs are resolved before revision checking: pending yields `message_in_progress`, complete yields the persisted completion, retryable failure reuses the turn and current revision, and non-retryable failure returns its stored error. A disconnect never cancels accepted work.
