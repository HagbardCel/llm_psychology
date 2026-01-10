# LLM API Key Rotation Implementation Plan

**Request**: support a list of API keys and rotate on quota exhaustion, with user-visible errors and debug logging.  
**Constraint**: Docker-only commands (see `AGENTS.md`).  
**Primary goal**: avoid stalled workflows when a key hits quota while keeping the service layer lean.

---

## Objective

Implement a multi-key Gemini configuration and rotation mechanism so:
- keys are configured only via `GOOGLE_API_KEYS` (list format),
- quota exhaustion rotates to the next key,
- all keys exhausted returns a clear error to the user,
- logs explain key selection and rotation without exposing secrets.

---

## Non-goals

- Legacy compatibility with single-key configuration.
- Provider changes or new LLM backends.
- Contract changes or UI redesign.

---

## Scope (Files Likely Touched)

Backend config + DI:
- `src/psychoanalyst_app/config.py`
- `src/psychoanalyst_app/container/service_container.py`
- `src/psychoanalyst_app/e2e_server.py`

LLM service + errors:
- `src/psychoanalyst_app/services/llm_service.py`
- `src/psychoanalyst_app/exceptions.py`

User-visible error handling:
- `src/psychoanalyst_app/orchestration/trio_conversation_manager.py`
- any agent/orchestrator path that does non-streaming LLM calls

Docs + env:
- `.env`
- `.env.usertest`
- `.env.example`
- `.env.usertest.template`
- `docs/README.md`
- `docs/QUICKSTART.md`
- `docs/design-principles.md`
- `Makefile`
- `deployment_validation.py`
- tests that reference `GOOGLE_API_KEYS`

---

## Key Decisions

### D1: Configuration format (no legacy support)
- `GOOGLE_API_KEYS` is the only supported variable.
- Format: JSON list string. Example: `GOOGLE_API_KEYS=["key1","key2"]`.
- A single key must still be expressed via `GOOGLE_API_KEYS`.

### D2: Rotation trigger
- Rotate only on Gemini quota exhaustion (429 / ResourceExhausted with quota text).

### D3: Exhaustion behavior
- If all keys are exhausted, raise a dedicated exception and surface a user error.

### D4: Logging
- Debug logs for key selection, rotation, and exhaustion.
- LLM call logs include `key_index` only, never the raw key.

---

## Implementation Plan

### P1) Configuration updates

Tasks:
- Replace `GOOGLE_API_KEYS: list[str]` in `Settings` and remove legacy usage.
- Add a `get_google_api_keys()` helper that:
  - parses comma-separated strings into a list,
  - strips whitespace and removes empty entries,
  - raises a clear error if the list is empty.
- Remove any use of legacy single-key configuration from code and tests.

Acceptance criteria:
- App fails fast with a clear config error if `GOOGLE_API_KEYS` is missing.
- Tests and tools only refer to `GOOGLE_API_KEYS`.

---

### P2) LLM service rotation

Tasks:
- Update `LLMService` to accept `api_keys: list[str]`.
- Create one `ChatGoogleGenerativeAI` client per key and keep them in a list.
- Track `current_key_index` and `exhausted_keys`.
- Add a thread-safe rotation lock (use `threading.Lock`).
- Wrap each LLM call path in a retry loop:
  - call using current key,
  - on quota exhaustion, mark key exhausted and rotate,
  - if all keys exhausted, raise `LLMQuotaExhaustedError`.
- Add debug logs for key selection and rotation.
- Include `key_index` in `_log_llm_call()` payload.

Acceptance criteria:
- Quota exhaustion on key 0 retries on key 1.
- All-keys-exhausted raises a dedicated exception.
- Debug logs show key index transitions.

---

### P3) DI wiring

Tasks:
- In `ServiceContainer`, pass `settings.get_google_api_keys()` into `LLMService`.
- Log how many keys are configured when creating the service.
- Update `e2e_server.py` to populate `GOOGLE_API_KEYS` with a dummy list.

Acceptance criteria:
- All agent-specific LLM services share the same key pool per model.
- Container no longer checks legacy single-key configuration.

---

### P4) User-visible errors

Tasks:
- Add `LLMQuotaExhaustedError` in `src/psychoanalyst_app/exceptions.py`.
- In `TrioConversationManager.stream_response`, catch it and return a clear
  user message ("All LLM keys are out of quota. Please try again later.").
- For non-streaming LLM calls (assessment, reflection, planning), catch the
  exception, avoid state transitions, and return a user-visible error.

Acceptance criteria:
- Console UI receives a clear error instead of hanging.
- Workflow state is not advanced when output is missing.

---

### P5) Docs and env files

Tasks:
- Update `.env`, `.env.usertest`, `.env.example`, `.env.usertest.template`
  to use `GOOGLE_API_KEYS`.
- Update docs and checks to reference only `GOOGLE_API_KEYS`.

Acceptance criteria:
- No references to legacy single-key configuration remain in current docs or env templates.
- Makefile/deployment validation accepts only `GOOGLE_API_KEYS`.

---

### P6) Tests

Tasks:
- Update tests to set `GOOGLE_API_KEYS` in fixtures.
- Add unit tests for parsing and rotation:
  - one key in list,
  - multi-key rotation on quota exhaustion,
  - all keys exhausted path.

Acceptance criteria:
- Tests pass without real API keys.

---

## Validation Checklist (Docker-only)

- `docker compose run --rm api pytest tests/unit/test_multi_model_config.py`
- `docker compose run --rm api pytest tests/unit/test_llm_key_rotation.py` (new)
- `docker compose run --rm api pytest tests/unit/test_trio_conversation_manager.py` (if updated)
