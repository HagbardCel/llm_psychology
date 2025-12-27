# Phase 4 — True Streaming + Shared Utilities (Detailed Implementation Plan)

Source: `docs/assessments/project/CODEBASE_ASSESSMENT_2025-12-16.md` (Phase 4 — True Streaming + Shared Utilities)

## Objective

Deliver **real-time** LLM streaming (first chunk arrives quickly, then incremental chunks) and reduce duplication by extracting a small set of “shared utilities” that are currently copy/pasted across the backend.

This phase should be high-leverage and low-risk: it should primarily change *how* work is streamed/formatted/serialized, not *what* the product does.

## Inputs and Constraints (Carry-Forward From Phases 1–3)

### Phase 1 Contract Decisions (must remain true)
- **D1 (Field naming)**: HTTP DTOs use `snake_case` keys end-to-end; generated TypeScript preserves wire keys.
- **D2 (Datetimes)**: HTTP datetimes are ISO 8601 strings; frontend types keep them as `string` (no implicit decoding).

Phase 4 utilities must not introduce new conversion/mapping layers that undermine D1/D2.

### Phase 2 Workflow Decision (must remain true)
- Proceed with **backend-driven navigation** using `POST /api/workflow/next-action`.
- WebSocket workflow/session behavior (e.g. `session_type`, assessment recommendations messages) must not regress.

### Phase 3 DI/Composition Target (must remain true)
- The DI container is the composition root; no new module-level runtime singletons.
- Agent-specific LLM selection is consistent (the instance used by agents and by streaming is the same).

## Non-goals (Explicitly Out of Scope)
- Changing the HTTP API contract (Phase 1).
- Changing workflow routing semantics or adding new workflow pages (Phase 2).
- Large module splits (Phase 5).
- A full WebSocket protocol redesign (keep `type` + `data` and existing message types stable).

## Phase 4 Scope (What We Touch)

### Streaming path
- `src/services/llm_service.py` (today: “paper streaming” returns `list[str]`)
- `src/orchestration/trio_conversation_manager.py` (today: awaits full chunk list before yielding)
- Potentially `src/psychoanalyst_app/testing/fakes.py` (keep deterministic streaming compatible with the updated interface)

### Shared utilities
- DB JSON serialization/deserialization used by `src/services/trio_db_service.py`
- Prompt composition helpers for therapy session start/resumption and “session briefing”-based prompts:
  - `src/agents/trio_psychoanalyst_agent.py`
  - `src/prompts/psychoanalyst_prompts.py` (and optionally adjacent prompt modules)
- WebSocket message envelope helpers used in:
  - `src/trio_server.py`
  - `src/orchestration/trio_conversation_manager.py`

## Key Decisions (Lock These Early)

### D4.1 Streaming API shape (compatibility vs correctness)
Pick one:

**Option A (recommended): add a new async streaming method**
- Keep the existing `LLMService.generate_response_stream(...) -> list[str]` (temporarily) for compatibility.
- Introduce a new method (name bikeshed):
  - `LLMService.stream_response(...) -> AsyncIterator[str]`
  - or `LLMService.generate_response_stream_iter(...) -> AsyncIterator[str]`
- Update `TrioConversationManager` to use the async iterator when available.

Pros: minimal breakage, easier staged rollout, safer for tests.
Cons: two APIs exist briefly.

**Option B: change `generate_response_stream` into an async generator**
- Update all call sites and test fakes in one PR.

Pros: one API.
Cons: higher blast radius; riskier in a refactor-heavy codebase.

This plan proceeds with **Option A**.

### D4.2 Backpressure + buffering
- Use a `trio.MemoryChannel` between the worker thread (LangChain stream) and Trio async consumer.
- Start with a small buffer (e.g. capacity `1–10`) to avoid unbounded memory growth if the consumer is slow.

### D4.3 Cancellation + disconnect behavior
- If the client disconnects / the consumer stops reading:
  - the receive side closes,
  - the sender stops producing (thread should detect `BrokenResourceError` and exit).
- Favor “best-effort stop” over perfect cancellation of the underlying LangChain call.

### D4.4 User-visible errors during streaming
- Do **not** stream raw stack traces into the chat stream.
- Log stack traces; send a short user-safe message (still local-only, but avoid “scary UX”).

## Implementation Plan

### P4.1 Introduce a Trio streaming bridge utility (single reusable primitive)

Create a tiny utility that converts a blocking iterator of strings into an `AsyncIterator[str]`:
- Suggested module: `src/utils/trio_streaming.py`
- Suggested API:
  - `async def iter_in_thread(iterator_factory: Callable[[], Iterator[str]], *, buffer_size: int = 1) -> AsyncIterator[str]`
  - or `async def stream_via_memory_channel(run_blocking: Callable[[SendChannel[str]], None], ...) -> AsyncIterator[str]`

Implementation sketch (conceptual):
- Create `send, receive = trio.open_memory_channel[str](buffer_size)`
- Start a worker in `trio.to_thread.run_sync(...)` that:
  - iterates the blocking stream,
  - pushes chunks to Trio using `trio.from_thread.run(send.send, chunk)`,
  - closes the channel when complete (or on error).
- The async side yields from `receive`.

Acceptance:
- A consumer can `async for` chunks and observe them incrementally (not all-at-once).
- When the consumer stops early, the producer exits without hanging.

### P4.2 Add true streaming to `LLMService` using the bridge

Update `src/services/llm_service.py`:
- Add `stream_response(...) -> AsyncIterator[str]` that:
  - applies rate limiting once per request (`await _acquire_rate_limit()`),
  - builds LangChain messages the same way as today,
  - streams chunks via the bridge.
- Keep `generate_response_stream(...) -> list[str]` for now but implement it as a compatibility wrapper:
  - collect chunks from `stream_response` into a list and return it.
- Ensure exception handling:
  - log full stack trace,
  - raise `LLMServiceError` with a short message (no multi-page stack traces intended for UI).

Acceptance:
- `stream_response` yields the first non-empty chunk quickly (subject to provider latency).
- Existing call sites that still use `generate_response_stream` continue to work.

### P4.3 Update deterministic/no-network fakes to match the streaming interface

Update `src/psychoanalyst_app/testing/fakes.py::DeterministicLLMService`:
- Add `stream_response(...) -> AsyncIterator[str]` that yields 2–5 deterministic chunks.
- Keep the existing `generate_response_stream(...) -> list[str]` as a wrapper to remain drop-in compatible.

Acceptance:
- CI/E2E stays no-network and still exercises streaming paths.

### P4.4 Update `TrioConversationManager` to yield chunks as they arrive

Update `src/orchestration/trio_conversation_manager.py`:
- Replace `_stream_llm_response()` implementation to use `llm_service.stream_response(...)` (new API).
- Ensure completion semantics remain stable:
  - the WS layer should still send a final `chat_response_chunk` with `is_complete=true`.
- Error handling:
  - stop sending stack traces as chat content,
  - send a single short error chunk and complete (or send an `error` message, but be consistent with existing clients).

Acceptance:
- No awaiting of “all chunks” before the first yield.
- Existing WS protocol tests still pass (`tests/integration/test_websocket_protocol_contract.py`).

### P4.5 Tighten WebSocket “envelope” creation (reduce repeated JSON dict literals)

Create a small helper for `{"type": ..., "data": ...}` construction:
- Suggested module: `src/utils/ws_messages.py`
- Suggested API:
  - `def ws_message(message_type: str, data: dict[str, Any] | None = None) -> dict[str, Any]`
  - Optional typed builders for common messages (recommended for server correctness):
    - `connected_message(user_id, name, status)`
    - `session_started_message(session_info)`
    - `chat_chunk_message(chunk, *, is_complete)`

Refactor call sites to use helpers:
- `src/trio_server.py` (connected/session_started/chat_response_chunk)
- `src/orchestration/trio_conversation_manager.py` (typing_start/stop/chat chunks/arbitrary messages)

Acceptance:
- No protocol changes (same `type` strings and payload shapes).
- Fewer “hand-rolled” message dicts; easier to keep consistent.

### P4.6 Extract DB JSON serialization helpers (centralize parsing/formatting)

Problem: `src/services/trio_db_service.py` repeats `json.dumps/json.loads` patterns for:
- session transcripts (`Message[]`)
- topics (`Topic[]`)
- tiered enrichment arrays (`dominant_affects`, `key_themes`)
- therapy plan JSON fields (`plan_details`, `initial_goals`, `planned_interventions`, `session_briefing`)

Plan:
- Create a helper module, e.g. `src/services/db_serialization.py`, with focused functions:
  - `dump_messages(messages: list[Message]) -> str`
  - `load_messages(payload: str | None) -> list[Message]`
  - `dump_topics(topics: list[Topic]) -> str`
  - `load_topics(payload: str | None) -> list[Topic]`
  - `dump_json(value: Any) -> str`
  - `load_json(payload: str | None, default: T) -> T`
- Update `src/services/trio_db_service.py` to call helpers instead of inlining loops.
- Keep behavior unchanged (same DB schema, same JSON shapes stored in SQLite).

Acceptance:
- `trio_db_service` still round-trips sessions/plans identically.
- Fewer custom loops and one-off `json.loads(...)` blocks.

### P4.7 Extract prompt composition helpers (resumption/session briefing)

Problem: therapy prompts are assembled in multiple steps with formatting-heavy code, making it easy to drift.

Plan:
- Create a prompt builder module under `src/prompts/`, e.g. `src/prompts/psychoanalyst_prompt_builder.py`, that is **pure formatting**:
  - Inputs: `UserProfile`, `TherapyPlan`, optional `SessionBriefing` dict, optional patient context string, optional knowledge snippets, and already-resolved `style_instructions`
  - Output: final prompt string(s)
- Refactor `src/agents/trio_psychoanalyst_agent.py`:
  - Keep I/O (RAG retrieval, DB lookups, briefing freshness checks) in the agent,
  - Move formatting/templating into the builder.
- Do not change the meaning of prompts in this phase; focus on consolidating composition and reducing duplication.

Acceptance:
- `TrioPsychoanalystAgent` prompt methods become shorter and easier to test.
- Prompt construction is centralized and consistent for:
  - first session greeting
  - resumption greeting (with session briefing)
  - continuation prompt (RAG + plan context)

### P4.8 Tests and validation upgrades (prove it’s “true streaming”)

Add/adjust tests to catch regressions that “paper streaming” previously masked.

Recommended tests:
- Unit test for the bridge utility (`src/utils/trio_streaming.py`):
  - Use a blocking generator that sleeps between yields (e.g. `time.sleep(0.05)`)
  - Assert that the async consumer receives at least one chunk before the generator completes.
- Integration test (optional but high value):
  - Wire a slow-streaming fake LLM into the container for the test server
  - Assert the first `chat_response_chunk` arrives within a short timeout, while the full response takes longer.

Validation checklist (local):
- `pytest -q tests/integration/test_websocket_protocol_contract.py`
- `pytest -q tests/integration/test_trio_flow.py` (or the repo’s standard integration subset)

## Suggested PR Breakdown (Minimize Risk)

1) **PR 1 — Streaming bridge + LLMService async stream API**
   - Add `src/utils/trio_streaming.py`
   - Add `LLMService.stream_response(...)`
   - Update `DeterministicLLMService` to support it

2) **PR 2 — Conversation manager uses true streaming**
   - Update `src/orchestration/trio_conversation_manager.py`
   - Keep WebSocket protocol stable; update/extend tests if needed

3) **PR 3 — WS envelope helpers**
   - Add `src/utils/ws_messages.py`
   - Refactor `src/trio_server.py` and conversation manager to use it

4) **PR 4 — DB serialization helpers**
   - Add `src/services/db_serialization.py`
   - Refactor `src/services/trio_db_service.py` to use helpers

5) **PR 5 — Prompt composition helpers**
   - Add `src/prompts/psychoanalyst_prompt_builder.py`
   - Refactor `src/agents/trio_psychoanalyst_agent.py` to use it

## Exit Criteria (Phase 4 is Done When…)

- **True streaming**: the first chunk reaches the client quickly; responses are delivered incrementally (no “await full completion before yielding” anywhere in the path).
- **WS protocol stable**: existing clients and `docs/WEBSOCKET_PROTOCOL.md` remain valid without changes.
- **Duplication reduced**: DB JSON parsing/formatting, WebSocket envelopes, and therapy prompt composition are centralized in small helpers.
- **No regressions to Phases 1–3**: HTTP DTO contract stays stable, workflow navigation stays consistent, and DI remains the composition root.

