---
owner: engineering
status: supporting
last_reviewed: 2026-07-11
review_cycle_days: 30
source_of_truth_for: Planned technology and third-party library choices for the single-user simplification refactor
---

# Technology and Library Decisions

> Planning document. These choices supplement `target-architecture.md`. They are binding for the refactor unless a focused compatibility spike demonstrates that a selected library does not work reliably with the actual local model/runtime.

## Decision principles

Third-party libraries should remove protocol, validation, networking, or persistence boilerplate without taking ownership of the product workflow.

The refactor should therefore:

- prefer small, focused libraries over broad agent frameworks;
- keep workflow progression, therapeutic phase coordination, and persistence semantics in project-owned application code;
- keep third-party types behind narrow project-owned boundaries;
- adopt at most one higher-level structured-output abstraction;
- remove dependencies that are retained only for speculative provider or framework flexibility;
- avoid stacked retry, scheduling, dependency-injection, and persistence abstractions;
- default to local operation without telemetry or remote services.

## Selected baseline stack

| Concern | Selected library | Intended use |
|---|---|---|
| HTTP API and WebSockets | `fastapi` | Typed HTTP routes, WebSocket endpoint, lifecycle hooks, error mapping, and OpenAPI generation |
| ASGI server | `uvicorn[standard]` | Local API process |
| Validation and contracts | `pydantic` | Domain values, API DTOs, persisted JSON documents, and structured LLM outputs |
| Configuration | `pydantic-settings` | Environment and `.env` configuration validation |
| OpenAI-compatible LLM transport | `openai` | Async streaming and non-streaming calls to llama.cpp, LM Studio, OpenRouter, and equivalent endpoints |
| Structured LLM output | `instructor`, subject to the compatibility spike below | Pydantic-validated structured generation and bounded validation retries |
| Console HTTP client | `httpx` | One reusable async API client with connection pooling and explicit timeouts |
| Console WebSocket client | `websockets` | Chat streaming and snapshot/operation notifications |
| Async SQLite access | `aiosqlite` | One connection/request queue without a custom executor or connection-pool abstraction |
| Async tests | `pytest` and `pytest-asyncio` | Unit, application, API, WebSocket, and persistence tests |
| Static checks | `ruff` and `mypy` | Formatting/linting and type checking |

`uv` remains the preferred dependency and execution tool. The lockfile, rather than broad runtime compatibility code, should make builds reproducible.

## LLM implementation decision

Application and phase code depend only on the project-owned `LLMGateway` protocol defined in `target-architecture.md`.

The initial concrete implementation is `OpenAICompatibleGateway` built on `openai.AsyncOpenAI`:

```python
client = AsyncOpenAI(
    base_url=settings.llm_base_url,
    api_key=settings.llm_api_key or "not-needed",
    timeout=settings.llm_timeout_seconds,
    max_retries=settings.llm_transport_retries,
)
```

The gateway exposes two product-level operations:

- `stream_text(...)` for interactive therapist responses;
- `generate_structured(...)` for intake patches, assessments, profile/plan updates, and post-session results.

Only modules under `llm/` may import `openai` or `instructor`. Provider response objects, SDK message classes, tool-call objects, and Instructor-specific configuration must not leak into phases, application services, persistence, API contracts, or tests.

The initial provider scope is deliberately narrow:

- llama.cpp through its OpenAI-compatible endpoint;
- LM Studio through its OpenAI-compatible endpoint;
- OpenRouter through its OpenAI-compatible endpoint;
- other compatible endpoints through configuration.

Native provider adapters are added only for a demonstrated capability that cannot be expressed through the OpenAI-compatible API.

## Instructor compatibility gate

`instructor` is the preferred structured-output helper, but it must not become mandatory until a short spike passes against the actual local server and representative model.

The spike must validate all of the following:

1. `IntakeRecordPatch` generation from representative intake turns.
2. `AssessmentResult` generation from a completed synthetic intake.
3. `PostSessionResult` generation from a representative therapy transcript.
4. Correct handling of markdown fences, malformed JSON, missing required fields, and invalid enum/value constraints.
5. Bounded validation retries with observable attempt counts and no unbounded retry nesting.
6. Compatibility with the chosen llama.cpp structured-output mode: native JSON schema/tool calling where reliable, otherwise explicit prompted JSON.
7. Compatibility with thinking-mode request parameters and any required `extra_body` configuration.
8. Cancellation, timeout, and error translation through the project-owned `LLMGateway` exceptions.
9. No persistence or workflow transition before the final structured result validates.

Acceptance thresholds:

- deterministic fixture suite passes without manual output repair;
- malformed-output tests terminate within the configured retry bound;
- the adapter remains materially smaller than a project-owned JSON extraction/retry implementation;
- structured-output configuration remains confined to `llm/structured.py`.

If the spike fails, keep `AsyncOpenAI` and implement one small project-owned structured-output adapter. Do not replace Instructor with a broader agent framework merely to obtain structured outputs.

## Frameworks not adopted

### LangChain and LangGraph

Do not use LangChain or LangGraph as the foundation of the refactor.

The product has an explicit workflow owned by `TherapyApplication`:

```text
intake → assessment → style selection → therapy → post-session processing
```

LangChain/LangGraph would introduce a second orchestration, state, middleware, retry, and persistence model around a workflow that should remain ordinary typed application code. The current repository uses LangChain primarily as provider/message wrappers rather than for tools, chains, retrieval, or graph execution. The refactor should replace that narrow use with `AsyncOpenAI` rather than expand the framework's role.

Required outcome:

- no `langchain*` runtime dependency;
- no LangChain message or runnable types in project contracts;
- no LangGraph state graph or checkpoint store;
- no framework-defined agent loop around therapeutic phases.

### PydanticAI

Do not adopt PydanticAI initially. It is a better fit than LangChain for typed Python, but its agent/tool abstractions are unnecessary for deterministic phase processors.

Reconsider it only when there is a concrete requirement for model-selected tools, iterative agent loops, MCP integration, or a capability that demonstrably replaces more project code than it introduces.

Do not combine PydanticAI with Instructor and LangChain.

### LiteLLM

Do not adopt LiteLLM initially. One local OpenAI-compatible endpoint plus OpenRouter does not require multi-provider routing, load balancing, cost routing, or fallback infrastructure.

Reconsider it only when the application actively operates multiple incompatible providers or deployments.

### ORM and migration frameworks

Do not add SQLAlchemy, SQLModel, or Alembic for the target six-table SQLite schema.

Use explicit SQL behind `SQLiteStore`, Pydantic validation for JSON payloads, and a clean schema recreation during this refactor. Revisit an ORM only if relational querying and schema evolution become materially more complex after the new architecture is established.

### Dependency-injection and plugin frameworks

Do not add a DI container, service registry, plugin registry, or entry-point framework. Construct the store, gateway, processors, and application explicitly in one composition root.

## Conditional libraries

These are not baseline dependencies.

### `aiolimiter`

Use only if direct cloud-provider operation needs a client-side requests-per-minute policy. Local endpoints should not be artificially rate-limited.

Do not implement another custom token bucket. Do not combine application rate-limit retries with multiple nested SDK/structured-output retries without an explicit total-attempt budget.

### `structlog`

Consider only after the new command/operation/LLM tracing boundaries exist. Adopt it only if it removes measurable manual JSON logging and context-propagation code. Standard-library structured logging is acceptable for the initial implementation.

### `tenacity`

Do not add initially. The OpenAI SDK already provides bounded transport retries, and Instructor may provide validation retries.

Add Tenacity only for a specific uncovered operation and document the total retry budget. Avoid:

```text
application retry → Tenacity retry → Instructor retry → SDK retry
```

## API and client library boundaries

- Only `api/` imports FastAPI/Starlette request, response, dependency, and WebSocket types.
- Only `client/` imports HTTPX and the WebSocket client library.
- Console presentation code depends on `JungApiClient`, not directly on HTTPX or WebSocket protocol details.
- API DTOs are project-owned Pydantic models; they must not reuse provider or database row types.
- FastAPI dependency injection is limited to API-boundary concerns such as obtaining the singleton application instance. It is not the application composition mechanism.

## Persistence library boundary

Only `persistence/sqlite_store.py` and tightly related persistence helpers may import `aiosqlite`.

Use:

- one explicitly managed connection or deliberately small connection strategy;
- explicit transaction scopes around application use cases;
- SQLite constraints for uniqueness and idempotency;
- temporary databases for tests;
- no repository-per-table hierarchy;
- no generic executor or connection-pool facade.

## Retry and timeout ownership

Retry policy must be centralized and bounded:

- transport retries: OpenAI SDK configuration;
- structured validation retries: Instructor or the project-owned structured adapter;
- recoverable long-running workflow retries: persisted `Operation` state;
- no hidden processor-level retry loops.

Timeouts should be explicit by category:

- HTTP client timeout;
- WebSocket connect/heartbeat policy;
- LLM transport timeout;
- structured generation timeout;
- long-running operation deadline.

The implementation must document the maximum possible provider attempts for one logical application command.

## Proposed dependency set

Initial target:

```toml
[project]
dependencies = [
    "fastapi",
    "uvicorn[standard]",
    "pydantic",
    "pydantic-settings",
    "openai",
    "httpx",
    "websockets",
    "aiosqlite",
    "instructor",
]

[project.optional-dependencies]
dev = [
    "pytest",
    "pytest-asyncio",
    "ruff",
    "mypy",
]
```

`instructor` enters the final baseline only after the compatibility gate passes.

Likely removals from the current runtime dependency set:

```text
langchain-core
langchain-google-genai
langchain-ollama
langchain-openai
trio
quart
hypercorn
trio-websocket
quart-trio
quart-cors
python-dotenv
python-multipart
```

`python-multipart` should return only if a real form/file-upload endpoint requires it. `pydantic-settings` is sufficient for `.env` loading, so `python-dotenv` need not be a direct dependency.

## Dependency acceptance criteria

The dependency refactor is complete when:

- all runtime networking uses asyncio;
- the console reaches the backend only through HTTP/WebSocket;
- no LangChain, LangGraph, Trio, Quart, or Hypercorn imports remain;
- provider and structured-output library types remain inside `llm/`;
- FastAPI types remain inside `api/`;
- HTTPX/WebSocket client types remain inside `client/`;
- aiosqlite remains inside `persistence/`;
- deterministic fake-LLM tests do not import provider libraries;
- the local-model workflow probe passes against the selected OpenAI-compatible endpoint;
- the resulting LLM layer is smaller and easier to test than the current provider/rate-limit/key-rotation service;
- unused optional provider, retry, telemetry, and framework dependencies are absent from the lockfile.
