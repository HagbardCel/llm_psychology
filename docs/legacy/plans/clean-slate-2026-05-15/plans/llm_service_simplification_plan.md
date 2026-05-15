# Plan: Simplify `llm_service.py` and prepare for Gemini + OpenRouter

## Goals
- Reduce complexity while keeping features: **streaming**, **structured output**, **audit logging**.
- Make the service **Trio-friendly** (no accidental blocking).
- Enable multiple providers: **Gemini now**, **OpenRouter later** (OpenAI-compatible).
- Let **LangChain handle** more: rate limiting, (optionally) retries and callbacks.

---

## 1) Make the API async-first
**Why:** Avoid blocking Trio and ensure one consistent path for rate limiting + logging.

### Actions
- Define these as the *primary* public methods:
  - `async invoke_text(prompt, context=None) -> str`
  - `async stream_text(prompt, context=None) -> AsyncIterator[str]`
  - `async invoke_structured(prompt, schema, method="json_schema") -> Any`
- Keep sync methods only as *compatibility*, or make them private:
  - `generate_response(...)` (sync)
  - Deprecate or document clearly: “Do not call from Trio tasks”.

### Migration
- Update call sites in the app to use the async methods.
- Optionally delete sync methods once migrated.

---

## 2) Centralize context → messages conversion
**Why:** Remove duplication and keep role mapping consistent.

### Actions
- Add a helper:
  - `_build_messages(prompt, context) -> list[BaseMessage]`
- Replace message-building logic in both:
  - non-streaming calls
  - streaming calls

### Result
- One place to handle roles (`system/user/assistant`) and future extensions.

---

## 3) Replace custom Trio rate limiter with LangChain’s rate limiter
**Why:** Remove a large chunk of custom code; keep consistent behavior across providers.

### Actions
- Remove:
  - `TrioRateLimiter`
  - `_acquire_rate_limit()`
  - any direct `await _acquire_rate_limit()` calls
- Create a LangChain limiter in `__init__`:
  - Convert `requests_per_minute` → `requests_per_second = rpm / 60`
  - Use `burst_capacity` as `max_bucket_size`
- Pass it into the model constructor:
  - `rate_limiter=InMemoryRateLimiter(...)`

### Notes
- This rate limiting is per-process memory (good enough for single instance).
- If you later run multiple replicas, rate limiting must move to a shared store.

---

## 4) Remove `LLMChain` and simplify prompt “chains”
**Why:** `LLMChain` is legacy-ish; you only need prompt formatting + calling.

### Actions
- Delete import:
  - `from langchain_classic.chains import LLMChain`
- Replace `run_prompt_chain(...)` with:
  1. `formatted = prompt_template.format(**inputs)`
  2. `await invoke_text(formatted, context=...)`

### Optional
- Keep `PromptTemplate` or replace it with standard Python `.format()` if preferred.

---

## 5) Consolidate error handling and JSONL logging
**Why:** Reduce repeated try/except + traceback boilerplate and keep logging consistent.

### Actions
- Keep:
  - `_get_llm_call_logger()`
  - `_log_llm_call(event, payload)`
- Add configuration switches (constructor args or config object):
  - `log_prompts: bool`
  - `log_responses: bool`
  - `redact_logs: bool` (recommended default **True** in production)
- Add one helper:
  - `_raise_llm_error(call_type, exc) -> LLMServiceError`
  - Used by all methods

### Optional hardening
- Redact or hash sensitive fields (session text/journals) by default.

---

## 6) Introduce a provider abstraction for Gemini + OpenRouter
**Why:** Avoid provider-specific branches everywhere.

### Actions
- Create a config object (dataclass or dict), e.g.:
  - `provider: "gemini" | "openrouter"`
  - `model_name`
  - `api_key`
  - `temperature`
  - `base_url` (optional; OpenRouter default)
  - rate limit + logging flags
- Add a single factory method:
  - `_create_llm(config, rate_limiter)`

### Provider implementations
- **Gemini**
  - `ChatGoogleGenerativeAI(model=..., google_api_key=..., temperature=..., rate_limiter=...)`
- **OpenRouter (OpenAI-compatible)**
  - Use `langchain_openai.ChatOpenAI` with:
    - `base_url="https://openrouter.ai/api/v1"`
    - `api_key=...`
    - `model=...`
    - `temperature=...`
    - `rate_limiter=...`

### Dependencies
- Add: `langchain-openai`
- Keep: `langchain-google-genai`, `langchain-core`

---

## 7) Keep Trio streaming bridge, but streamline it
**Why:** LangChain streaming is typically blocking; Trio needs a bridge.

### Actions
- Keep the pattern:
  - define a small iterator closure that calls `self.llm.stream(messages)`
  - bridge to Trio with `iter_in_thread(iterator, buffer_size=...)`
- Use `_build_messages()` to avoid duplication.
- Consider log volume:
  - optionally log every Nth chunk or only start/end events

---

## 8) Structured output: keep, but label “best effort” for OpenRouter
**Why:** Gemini structured outputs tend to be reliable; OpenRouter depends on the underlying model.

### Actions
- Keep:
  - `self.llm.with_structured_output(schema, method="json_schema").invoke(prompt)`
- Add docstring note:
  - “Reliability depends on provider/model.”

### Optional fallback (future)
If structured output fails:
1. Retry once with a stricter “JSON only” instruction
2. Parse with Pydantic (`model_validate_json`)
3. Raise a clear error if validation fails

---

## 9) Update wiring and call sites
**Why:** Ensure the rest of the app can select providers cleanly.

### Actions
- Introduce environment-based configuration:
  - `LLM_PROVIDER=gemini|openrouter`
  - `LLM_MODEL=...`
  - `LLM_API_KEY=...`
  - `OPENROUTER_BASE_URL` (optional)
- Update service construction to use the new config object.
- Ensure no call sites use sync methods from Trio tasks.

---

## 10) Tests (minimal but high-value)
### Unit tests
- `_build_messages()` converts roles correctly and preserves ordering.

### Integration/smoke tests (mocked LLM)
- `invoke_text()` returns `.content` correctly
- `stream_text()` yields multiple chunks in order
- structured output returns parsed object when model returns valid data

### Rate limiter tests
- When enabled, limiter instance exists and is passed into model constructor.

---

## Suggested migration order (safe, incremental)
1. Add `_build_messages()` and refactor invoke + stream to use it.
2. Replace `LLMChain` with “format + invoke”.
3. Add config object + `_create_llm()` with Gemini only.
4. Replace custom rate limiter with `InMemoryRateLimiter`.
5. Add OpenRouter backend via `ChatOpenAI`.
6. Flip codebase to async-first methods; deprecate/remove sync methods.

---
