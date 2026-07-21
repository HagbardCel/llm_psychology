---
owner: engineering
status: accepted
last_reviewed: 2026-07-21
review_cycle_days: 30
source_of_truth_for: Workflow, revision, operation, and chat-turn model
---

# ADR 0003: Stage, operations, and chat turns

## Decision

Persist one `Stage`: `SETUP → INTAKE → ASSESSMENT → STYLE_SELECTION → READY → THERAPY → POST_SESSION → READY`. Client commands are `update_profile`, `send_message`, `select_style`, `start_session`, `end_session`, and `retry_operation`. Intake completion is processor-driven during chat acceptance, not a separate client command.

`Operation` is reserved for assessment and post-session workflow work. A separate durable `ChatTurn` owns a user message and generated reply with `pending`, `complete`, or `failed` status. Every durable mutation increments snapshot revision.

## Chat idempotency

`send_message` includes `session_id`, `client_message_id`, `request_id`, and `expected_revision`. Known client-message IDs are looked up before revision validation: pending turns report in progress, complete turns return the stored result, and retryable failed turns regenerate without another user message. `request_id` is ephemeral correlation only.

## Consequences

Invalid commands return `invalid_command`; stale commands return `state_conflict`.

## Related canonical documentation

- [Workflow Specification](../refactor/workflow-specification.md)
