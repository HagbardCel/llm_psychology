---
owner: engineering
status: accepted
last_reviewed: 2026-07-12
review_cycle_days: 30
source_of_truth_for: Detailed implementation plan for architecture refactor Phase 3
---

# Architecture Refactor Phase 3 Implementation Plan

## 1. Phase objective

Phase 3 implements the target LLM boundary and ports the therapeutically meaningful behavior of the legacy agents into four narrow, typed phase processors:

- `IntakeProcessor`;
- `AssessmentProcessor`;
- `TherapyProcessor`;
- `PostSessionProcessor`.

The phase must establish the final model-facing architecture that Phase 4 can coordinate without carrying forward the legacy agent graph, service container, persistence access, workflow navigation, Trio runtime, or provider-specific abstractions.

At the end of Phase 3, the new package must contain:

- one project-owned `LLMGateway` protocol;
- one direct async OpenAI-compatible implementation;
- one deterministic `FakeLLM`;
- one compact set of task-specific model policies;
- one tracing wrapper around the gateway boundary;
- four independently testable processors with typed inputs and results;
- pure prompt, context, validation, merge, and policy helpers;
- no HTTP, WebSocket, application-task, or workflow-transition implementation.

**Step 0 (prerequisite):** limited completion of Phase 2 processor-facing persistence seams (`PlanContent`, durable intake record on sessions, optional post-session plan revision). This does not move application orchestration or ordinary processor persistence into Phase 3.

Phase 3 preserves product behavior where that behavior is therapeutically useful, but it does not preserve the legacy implementation topology. It deliberately replaces nested agents and generic response metadata with explicit processor contracts.

The accepted decisions in the following documents are binding:

- [Target Architecture](target-architecture.md);
- [Architecture Refactor Roadmap](architecture-refactor-roadmap.md);
- [Workflow Specification](workflow-specification.md);
- [API v1 Contract](api-v1-contract.md);
- [ADR 0002](../adr/0002-asyncio-fastapi-runtime.md);
- [ADR 0003](../adr/0003-workflow-stage-command-operation-model.md);
- [ADR 0004](../adr/0004-single-sqlite-store-and-schema-reset.md);
- [ADR 0005](../adr/0005-phase-processors-and-llm-gateway.md).

This plan translates those decisions into implementable Phase 3 work. It must not redefine the durable workflow, persistence schema, public API, or Phase 4 application lifecycle.

## 2. Desired implementation philosophy

### 2.1 Port behavior, not the agent framework

The current agents contain useful prompts, schemas, deterministic policies, and validation logic. They also contain infrastructure and orchestration responsibilities that do not belong in the target processors.

Port:

- therapeutically relevant prompt instructions;
- intake evidence and completion policy;
- structured extraction schemas that remain useful;
- therapy-style descriptions and instructions;
- session-context and plan-context formatting;
- assessment recommendation semantics;
- profile and plan patch semantics;
- session briefing and continuity behavior;
- useful LLM diagnostics.

Do not port:

- `AgentResponse`;
- `next_action`, workflow events, or state transitions;
- database reads or writes;
- user-scoped context services;
- processor-to-processor calls;
- agent factories or registries;
- service-locator lookups;
- per-agent LLM service objects;
- Trio nurseries, cancel scopes, thread bridges, or rate limiters;
- LangChain message and runnable types;
- RAG calls or placeholder retrieval abstractions;
- provider branches for Gemini, Ollama, LM Studio, and OpenAI-compatible endpoints;
- API-key rotation and cloud quota policy;
- health-check methods on each processor;
- friendly fallback strings that hide typed failures;
- tier/job/workflow metadata dictionaries.

The desired outcome is not a renamed agent hierarchy. It is a small set of typed functions and classes whose responsibilities can be understood from their method signatures.

### 2.2 Keep the new package final-form and isolated

Phase 3 code may coexist with the legacy runtime in the repository, but it must already use final target concepts and dependencies.

Do not introduce:

- `NewLLMService`, `V2Processor`, `TargetAgent`, or similar transitional names;
- adapters from new processors back into legacy agents;
- wrappers around the legacy `LLMService`;
- dual-mode processors that accept both target and legacy models;
- feature flags selecting legacy versus target LLM behavior;
- compatibility aliases for `AgentResponse` or legacy structured outputs;
- a second dependency-injection container.

The running legacy product remains unchanged during Phase 3. The new processors are exercised through focused unit and processor integration tests only. Phase 4 will make them executable as a complete application core.

### 2.3 Prefer one semantic operation over many specialized agents

The legacy architecture often decomposes one product operation into multiple cooperating agents. Phase 3 should consolidate those graphs into cohesive processor operations.

Examples:

- intake note extraction becomes an intake helper, not a `NoteTakerAgent`;
- initial plan material becomes part of assessment output, not a later planning-agent call;
- therapeutic memory becomes explicit input context, not a stateful `MemoryAgent` cache;
- reflection, summarization, profile updating, briefing generation, and plan updating become one `PostSessionProcessor` with a small number of structured calls;
- style loading becomes a pure catalog/resource loader, not a mutable service.

A helper is appropriate when it is pure, stateless, and independently testable. A helper must not become an orchestration object with its own dependencies and lifecycle.

### 2.4 Optimize for local model execution

The primary runtime is a local OpenAI-compatible model server. Design choices should therefore reduce latency, heat, and avoidable model calls without weakening typed validation.

Rules:

- make one model call when one model call can reliably produce one coherent typed result;
- avoid separate LLM calls for facts that deterministic policy can derive;
- avoid re-analyzing the same full transcript several times in one operation;
- pass compact intermediate structured results to later calls;
- use deterministic context limits rather than adding a tokenizer dependency;
- disable hidden SDK retries;
- make correction attempts explicit and observable;
- keep task-level model overrides configurable without constructing one service per task;
- support provider request extras through adapter configuration, not processor code.

### 2.5 Keep schemas strict but proportionate

Pydantic models are the processor contract and the structured-output validation boundary. They should reject unusable output without attempting to model every possible clinical nuance.

Prefer:

- bounded strings and lists;
- explicit optional fields;
- enums only where the allowed vocabulary is stable and useful;
- patch models for updates;
- deterministic post-validation and normalization;
- meaningful validation errors included in one correction attempt.

Avoid:

- deeply nested tier structures retained only for compatibility;
- generic `dict[str, Any]` processor results;
- schemas so large that local models regularly fail to produce them;
- silent coercion of invalid content into defaults that look successful;
- third-party JSON-repair libraries.

### 2.6 Fail explicitly at the model boundary

Processors must not convert infrastructure or validation failures into ordinary therapeutic text. They should propagate stable project errors:

- `llm_unavailable`;
- `llm_timeout`;
- `invalid_llm_output`.

Phase 4 will decide how failures affect `Operation` and `ChatTurn` lifecycle. Phase 5 will map them to API and WebSocket errors.

## 3. Scope

### 3.1 In scope

Phase 3 includes:

- project-owned chat message models;
- task names and model policies;
- structured-output mode selection;
- direct async OpenAI-compatible chat-completions integration;
- streaming text generation;
- structured generation with Pydantic validation;
- one correction attempt after invalid structured output;
- provider exception classification;
- gateway tracing and prompt-redaction policy;
- deterministic fake LLM behavior;
- packaged therapy-style loading;
- typed intake record, extraction, completion, and response preparation;
- typed assessment recommendations and initial-plan material;
- therapy prompt/context construction and streaming;
- typed post-session analysis, briefing, profile patch, and plan patch generation;
- pure merge and no-op detection helpers;
- shared domain `PlanContent` model;
- Step 0 store seams: `intake_record_json` on intake sessions, `complete_chat_turn` intake-record persistence, optional post-session plan revision via `NewPlanRevision`, compact store-derived post-session operation result;
- Phase 3 unit and processor tests;
- import-boundary validation;
- optional local-server smoke tests.

### 3.2 Out of scope

Phase 3 must not implement:

- `TherapyApplication`;
- application locking or task supervision;
- `EventStream`;
- operation scheduling or recovery;
- chat-turn acceptance or persistence (other than Step 0 `complete_chat_turn` intake-record extension);
- store transactions (other than the explicitly listed Step 0 seam corrections);
- HTTP routes;
- WebSocket events;
- FastAPI startup or lifespan;
- console changes;
- API DTOs or error mapping;
- database access from processors;
- workflow transitions;
- selection-command handling;
- session start/end handling;
- persistence of intake records, assessment results, profile patches, plans, or briefings (other than Step 0 seam corrections for intake record storage and optional post-session plan creation);
- migration or compatibility logic;
- deletion of the legacy agents or `LLMService`;
- production selection of the new package;
- generalized RAG;
- tool calling;
- Responses API support;
- multiple LLM providers or provider load balancing;
- cloud API-key rotation or rate limiting;
- autonomous agent routing;
- a generic prompt framework;
- a generic retry framework.

Phase 3 may define typed results that Phase 4 will persist, but it must not create a partial application service around those results.

## 4. Entry conditions

Phase 3 starts only after all Phase 2 exit criteria are satisfied. **Step 0** closes the processor/store seams identified during planning (intake record durability, `PlanContent`, optional post-session plan revision).

Required inputs from Phase 2:

- final target domain models;
- tested pure workflow policy;
- tested `SQLiteStore`;
- accepted `AppSnapshot`, `Operation`, `ChatTurn`, `Plan`, `Session`, `Message`, and profile semantics;
- stable validated JSON/document seams for processor-owned documents;
- stable error types or an agreed location for adding the LLM error subclasses;
- no legacy dependencies in the target package.

Repository conditions:

- Phase 1 characterization remains green;
- Phase 2 target tests remain green;
- no unresolved ADR-level question remains about processor or gateway ownership;
- no unrelated product work is mixed into the Phase 3 branch;
- the target package is still not imported by the running legacy runtime.

Recommended branch:

```text
refactor/phase-3-llm-processors
```

A stacked branch is acceptable, but the Phase 3 diff must remain reviewable as a processor/LLM change and must not include Phase 4 application orchestration.

## 5. Phase deliverables

Recommended minimal package shape:

```text
src/jung/
├── llm/
│   ├── __init__.py
│   ├── gateway.py
│   ├── openai_compatible.py
│   ├── structured.py
│   ├── tracing.py
│   └── fake.py
├── styles/
│   ├── __init__.py
│   ├── jung/
│   ├── cbt/
│   └── freud/
└── phases/
    ├── __init__.py
    ├── intake/
    │   ├── __init__.py
    │   ├── processor.py
    │   ├── models.py
    │   ├── prompts.py
    │   ├── completion.py
    │   └── merge.py
    ├── assessment/
    │   ├── __init__.py
    │   ├── processor.py
    │   ├── models.py
    │   └── prompts.py
    ├── therapy/
    │   ├── __init__.py
    │   ├── processor.py
    │   ├── models.py
    │   ├── prompts.py
    │   └── context.py
    └── post_session/
        ├── __init__.py
        ├── processor.py
        ├── models.py
        ├── prompts.py
        └── merge.py

tests/unit/jung/
├── llm/
│   ├── test_gateway_models.py
│   ├── test_openai_compatible.py
│   ├── test_structured_output.py
│   ├── test_tracing.py
│   └── test_fake_llm.py
├── phases/
│   ├── intake/
│   ├── assessment/
│   ├── therapy/
│   └── post_session/
└── test_styles.py

tests/integration/jung/
└── test_processor_contracts.py
```

This tree is a starting point, not a requirement to create every file immediately.

Consolidation rules:

- keep `gateway.py` limited to project-owned contracts;
- keep OpenAI SDK imports in `llm/` only;
- keep prompt strings close to their phase;
- keep pure intake evidence logic split if the existing logic remains independently testable;
- keep post-session merge/no-op logic pure;
- consolidate small models into the processor module until they justify a separate file;
- do not create empty `policy.py`, `summarizer.py`, `profile_updater.py`, or `plan_updater.py` placeholders;
- do not create an abstract base processor.

## 6. Target LLM contracts

### 6.1 Chat messages

Define one project-owned message type. Processor code must not import OpenAI or LangChain message classes.

Illustrative contract:

```python
class ChatRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(BaseModel):
    role: ChatRole
    content: str
```

Validation requirements:

- content is non-empty after trimming, except where a deliberately empty opening turn is represented outside the message list;
- no provider response object is stored on the model;
- no name, tool-call, or multimodal fields are added before a concrete use case requires them.

### 6.2 LLM task names

Replace the legacy list of fine-grained agent phases with a compact semantic task vocabulary.

Recommended initial tasks:

```text
intake_patch
intake_response
assessment
therapy_response
post_session_analysis
post_session_update
```

Use one `therapy_response` task for both opening and continuation turns unless measurements demonstrate that different policies are needed.

Do not retain separate task names for:

- memory agent;
- planning agent;
- reflection agent;
- note-taking agent;
- deep-topic detection;
- tier-specific change detection;
- session enrichment workers.

Those concepts are consolidated into the four processors.

### 6.3 Structured-output mode

```python
class StructuredOutputMode(StrEnum):
    JSON_SCHEMA = "json_schema"
    JSON_OBJECT = "json_object"
    PROMPT = "prompt"
```

Semantics:

- `JSON_SCHEMA`: send an OpenAI-compatible `response_format` JSON schema;
- `JSON_OBJECT`: request a JSON object and validate it locally against the Pydantic type;
- `PROMPT`: append a compact schema instruction and validate returned text locally.

Selection is configuration-driven. Processor code does not infer capability from provider name or base URL.

### 6.4 Model policy

Use one immutable project-owned policy per semantic task.

Illustrative contract:

```python
@dataclass(frozen=True, slots=True)
class ModelPolicy:
    task: LLMTask
    model: str
    temperature: float
    timeout_seconds: float
    max_completion_tokens: int | None = None
    structured_output_mode: StructuredOutputMode = StructuredOutputMode.PROMPT
```

Optional fields are acceptable only when immediately used by the adapter. Avoid a generic bag of provider options on `ModelPolicy`.

Recommended defaults:

- structured tasks: temperature `0.0` to `0.2`;
- therapy and intake response: temperature `0.5` to `0.8`;
- explicit finite timeout per task;
- no SDK retries;
- output-token limits set only when known to work across the supported local servers.

Per-task model overrides are resolved when policies are constructed. They do not create multiple gateway instances.

### 6.5 Gateway protocol

Use the accepted target protocol:

```python
T = TypeVar("T", bound=BaseModel)


class LLMGateway(Protocol):
    async def stream_text(
        self,
        messages: Sequence[ChatMessage],
        policy: ModelPolicy,
    ) -> AsyncIterator[str]: ...

    async def generate_structured(
        self,
        messages: Sequence[ChatMessage],
        output_type: type[T],
        policy: ModelPolicy,
    ) -> T: ...
```

Contract invariants:

- `stream_text` yields only non-empty text chunks;
- `generate_structured` returns an instance of the requested Pydantic type;
- the gateway never returns raw provider objects;
- the gateway never returns `dict[str, Any]` for typed generation;
- cancellation propagates naturally;
- provider exceptions are mapped to stable project errors;
- structured validation gets at most one correction attempt;
- the protocol contains no persistence, tracing, request ID, session ID, or API concepts.

Correlation data belongs in logging context or the tracing wrapper, not in processor contracts.

## 7. Workstream A — OpenAI-compatible gateway

### 7.1 Direct SDK integration

Implement `OpenAICompatibleLLM` with the async OpenAI Python SDK and Chat Completions-compatible endpoints.

Requirements:

- construct one `AsyncOpenAI` client;
- use `chat.completions.create` directly;
- set `max_retries=0` unless an accepted ADR changes the policy;
- convert project messages at the adapter boundary;
- pass the policy model explicitly on every request;
- keep base URL, API key, and adapter request extras in configuration;
- do not branch on `gemini`, `ollama`, `lmstudio`, or `llama.cpp` provider names;
- do not import LangChain;
- do not use a synchronous SDK or thread bridge.

The default local API key may be a configured placeholder such as `not-needed`, but the value must remain configuration-owned.

### 7.2 Adapter configuration

Use a small immutable configuration object containing only adapter-level concerns:

- `base_url`;
- `api_key`;
- optional default request headers;
- optional request `extra_body` mapping;
- optional per-task `extra_body` overrides when a current local-server feature requires them.

This is the appropriate seam for llama.cpp or LM Studio request extensions such as chat-template options. Processor and domain code must not know about `chat_template_kwargs`, `enable_thinking`, or other provider request fields.

Configuration rules:

- parse JSON configuration once at startup in Phase 4 composition;
- reject malformed mappings before the first model call;
- merge default and task-specific extras deterministically;
- never log secrets;
- do not create an extension plugin system.

### 7.3 Text streaming

`stream_text` should:

1. validate that messages are present;
2. build the Chat Completions request;
3. request streaming;
4. iterate asynchronously over provider chunks;
5. extract text deltas only;
6. ignore empty role/usage/control chunks;
7. yield text without buffering the entire answer;
8. preserve cancellation;
9. map provider failures to target errors.

Do not:

- collect all chunks before yielding;
- start detached tasks;
- retry a partially emitted stream;
- emit provider event objects;
- normalize whitespace across chunk boundaries;
- convert a failed stream into a normal fallback response.

A stream that fails after yielding tokens is still a failed generation. Phase 4 will mark the durable chat turn failed and will not persist the partial assistant response as complete.

### 7.4 Structured generation

`generate_structured` should:

1. validate that the policy is intended for structured use;
2. create the mode-specific request;
3. read the first complete response;
4. require text content;
5. strip a single surrounding Markdown JSON fence only as a defensive normalization;
6. validate with `output_type.model_validate_json(...)` or equivalent;
7. return the validated model;
8. on validation failure, make one explicit correction call;
9. validate the corrected response;
10. raise `invalid_llm_output` if correction fails.

The correction prompt must include:

- the requested schema name;
- the concise validation error path/message;
- the invalid response, bounded to a safe size;
- an instruction to return only corrected JSON.

The correction attempt must not include an unbounded traceback or duplicate the complete original conversation when a compact repair context is sufficient.

### 7.5 Native JSON schema mode

For `JSON_SCHEMA`, use the Pydantic JSON schema to build an OpenAI-compatible strict response format.

Required behavior:

- use a deterministic schema name;
- remove unsupported metadata only when a supported local server demonstrably requires it;
- keep the original Pydantic model as the final validator;
- do not assume that a provider accepting `response_format` guarantees valid output;
- cover llama.cpp/LM Studio compatibility in the optional smoke test.

### 7.6 JSON object mode

For `JSON_OBJECT`:

- send `response_format={"type": "json_object"}`;
- include a concise description of the expected fields in the system or final user instruction;
- validate against the requested Pydantic model;
- use the same correction path on failure.

### 7.7 Prompt-constrained mode

For `PROMPT`:

- append a compact, deterministic schema instruction;
- require JSON only, with no Markdown or commentary;
- avoid dumping excessive schema descriptions when they materially inflate prompts;
- retain field types, required fields, enum values, and important bounds;
- validate locally;
- use the same correction path.

Do not add a general JSON-repair dependency. A malformed response either validates after one correction or fails explicitly.

### 7.8 Error classification

Map SDK/provider failures to the target error taxonomy.

Minimum classification:

| Provider condition | Target error | Retryable in Phase 4 |
|---|---|---|
| connect/DNS/refused connection | `llm_unavailable` | yes |
| provider 5xx / temporary overload | `llm_unavailable` | yes |
| explicit SDK timeout | `llm_timeout` | yes |
| empty or non-text structured response | `invalid_llm_output` | no |
| Pydantic validation fails twice | `invalid_llm_output` | no |
| invalid local configuration or unsupported request shape | `llm_unavailable` with non-retryable diagnostic classification | normally no |

Raw provider response bodies, API keys, and full prompts must not appear in user-visible error messages.

### 7.9 Cancellation and shutdown semantics

The gateway must not shield model calls from cancellation. Phase 4 owns accepted-work lifecycle and shutdown policy.

Gateway requirements:

- cancellation exits the SDK iterator/call promptly where supported;
- no background task survives the awaiting caller;
- no thread remains blocked after cancellation because Phase 3 uses the async SDK;
- cleanup does not convert cancellation into `llm_unavailable`;
- client closure is exposed as an explicit async lifecycle method on the concrete adapter or owned directly by Phase 4 composition.

Do not add `close()` to the narrow `LLMGateway` protocol solely for one implementation. The composition root may own the concrete client's lifecycle.

## 8. Workstream B — Tracing and diagnostics

### 8.1 Tracing wrapper

Implement `TracingLLMGateway` as a decorator over `LLMGateway`.

It should record:

- semantic task;
- configured model;
- structured-output mode;
- call type (`stream_text` or `generate_structured`);
- start/finish/failure;
- latency;
- time to first chunk for streaming;
- emitted chunk count and completion character count;
- requested output model name;
- validation/correction outcome when exposed by the concrete structured helper;
- provider token usage when available without weakening the gateway contract;
- stable correlation context supplied through logging context by Phase 4.

The tracing wrapper must not:

- mutate messages;
- own retries;
- persist workflow state;
- emit API events;
- buffer a stream solely to calculate metrics;
- log complete prompts or responses by default.

### 8.2 Prompt and response logging

Default policy:

- log message count, role sequence, and character counts;
- log schema/model/task names;
- log bounded previews only when an explicit diagnostic setting is enabled;
- redact content by default;
- never log API keys or authorization headers;
- keep detailed LLM call logging opt-in.

A local debugging mode may record bounded prompt/response previews, but it must remain visibly enabled and must preserve existing redaction expectations.

### 8.3 No diagnostics in domain results

Do not add tracing metadata, model names, timings, or token counts to processor result models. Operational diagnostics remain logs/traces. They do not become persisted therapeutic documents or API fields.

## 9. Workstream C — Deterministic `FakeLLM`

### 9.1 Purpose

`FakeLLM` is the primary test double for all Phase 3 processor tests and later Phase 4 application integration tests.

It must implement the exact `LLMGateway` protocol and remain independent of network, SQLite, OpenAI SDK types, and timing.

### 9.2 Scripted interactions

Use a small queue of explicit expected interactions.

Suggested interaction types:

```text
StreamExpectation
StructuredExpectation[T]
FailureExpectation
```

Each expectation may contain:

- expected task;
- expected output model for structured calls;
- optional message predicate or required text fragments;
- response chunks or validated response model;
- optional stable error to raise.

Behavior:

- calls consume expectations in order;
- task or output-type mismatch fails the test immediately;
- stream chunks are yielded exactly as scripted;
- structured results are copied/validated to prevent accidental mutation;
- an assertion helper verifies that no expected calls remain.

Avoid:

- a programmable callback framework;
- matching complete prompt snapshots by default;
- implicit fallback responses;
- fuzzy task matching;
- sleeps that simulate latency in normal tests.

### 9.3 Failure scenarios

The fake must support deterministic:

- pre-stream `llm_unavailable`;
- pre-stream `llm_timeout`;
- mid-stream failure after one or more chunks;
- invalid structured output behavior when testing the concrete adapter separately;
- processor-visible typed gateway failures.

The fake should normally return already validated Pydantic models for structured processor tests. JSON parsing and correction belong to concrete gateway tests.

## 10. Workstream D — Therapy style catalog

### 10.1 Replace `StyleService` with a pure catalog

Define a small immutable `StyleDefinition` containing only fields used by target processors:

```text
id
name
description
assessment_instructions
therapist_instructions
post_session_instructions (optional)
```

Load definitions from packaged resources through one pure loader or small immutable `StyleCatalog`.

Required behavior:

- deterministic style ordering;
- explicit duplicate-ID rejection;
- required asset validation at load time;
- no mutable global cache;
- no RAG knowledge loading;
- no database access;
- no provider/model configuration;
- no user-specific state.

The composition root may load the catalog once and inject it into assessment and therapy processors.

### 10.2 Asset treatment

Retain and port:

- patient-facing descriptions;
- assessment instructions that materially distinguish styles;
- therapist system instructions;
- reflection/post-session instructions when still useful.

Do not make `knowledge.md` a required target asset. It may remain unused until Phase 6 deletion or a future concrete retrieval use case.

### 10.3 Style identifiers

Use stable lowercase identifiers already exposed to users where practical. Do not add aliases unless the API contract requires them.

Selection parsing does not belong in the style catalog. Phase 5 validates an explicit style ID from the API command.

## 11. Workstream E — `IntakeProcessor`

### 11.1 Responsibility

`IntakeProcessor` owns:

- intake prompt strategy;
- structured intake-record patch extraction;
- evidence validation and deterministic merge;
- intake completion policy;
- selection of the next missing/direct-ask topic;
- construction and streaming of the next intake response.

It does not own:

- profile persistence;
- message persistence;
- stage transition;
- creation of the assessment operation;
- session timing or ending;
- API metadata;
- generic workflow action strings.

### 11.2 Target input models

Define a typed `IntakeTurnInput` containing only data Phase 4 can load before calling the processor:

- editable profile fields required by the prompt;
- current validated `IntakeRecord`;
- ordered intake transcript;
- latest persisted user message;
- optional previous assistant message;
- configured intake requirements;
- optional primary language.

Do not pass:

- `user_id`;
- database service;
- `ConversationContext`;
- workflow state;
- WebSocket connection;
- mutable topic lists owned by orchestration.

### 11.3 Intake record and patch models

Port the useful current structured record and evidence semantics into phase-local target models.

Requirements:

- retain patient-grounded evidence references where they protect against hallucinated intake facts;
- identify evidence by stable message ID or transcript sequence, not by legacy list position alone;
- bound evidence quotes;
- represent missing/unknown/declined answers explicitly where necessary;
- use patch models with optional fields;
- reject patch fields unsupported by the current record schema;
- separate editable `Profile` from backend-owned intake/derived therapeutic data.

Do not copy the entire legacy patient tier model into the intake record.

### 11.4 Intake preparation contract

Use a two-step processor interface so Phase 4 can persist deterministic effects and supervise streaming without requiring an async generator to return a final value.

Illustrative interface:

```python
class IntakeProcessor:
    async def prepare_turn(self, input: IntakeTurnInput) -> IntakeTurnPlan: ...

    def stream_response(
        self,
        plan: IntakeTurnPlan,
    ) -> AsyncIterator[str]: ...
```

`IntakeTurnPlan` should contain:

- merged validated intake record;
- whether the record changed;
- deterministic completion decision;
- selected next required item, if any;
- typed evidence/merge diagnostics needed by tests and later observability;
- final LLM messages for the response stream.

The plan must not contain:

- `next_action`;
- workflow event;
- HTTP status;
- database mutation instructions;
- arbitrary metadata dictionaries.

Phase 4 will persist the record change, stream the response, complete the chat turn, and trigger `finish_intake` when the accepted result is complete.

### 11.5 Patch extraction

`prepare_turn` should make at most one structured `intake_patch` call for a non-empty patient turn.

The extraction prompt should include:

- current record summary;
- latest patient message;
- previous assistant question when available;
- evidence rules;
- explicit instruction not to infer unsupported facts;
- requested patch schema.

The model proposes a patch. Deterministic code decides whether evidence and values are acceptable.

### 11.6 Deterministic merge and evidence validation

Port and simplify the current useful logic from intake record merge/completeness modules.

Required invariants:

- only patient-authored text may support patient facts;
- evidence references must resolve to the supplied transcript;
- strict quote validation is deterministic and configurable only if the target still requires a relaxed test mode;
- a failed extraction does not erase the prior record;
- an empty valid patch is distinguishable from invalid output;
- merge is pure and idempotent;
- repeated processing of the same proposed patch produces the same record;
- diagnostics are bounded and typed.

### 11.7 Completion policy

The LLM must not decide whether intake is complete.

Completion is a pure function of:

- required record fields;
- evidence requirements;
- explicit unknown/declined policy;
- safety-screen policy;
- configured maximum-turn escape behavior, if retained.

If a maximum-turn completion rule remains, extraction failure on the final turn must not incorrectly mark an incomplete stale record complete. Preserve the current safeguard that differentiates genuine completion from a stale-record max-turn escape.

### 11.8 Response prompt and streaming

The intake response prompt should be built from:

- compact profile information;
- current record summary;
- latest patient message and bounded recent context;
- next required item or closing intent;
- safety instruction;
- primary-language instruction.

Rules:

- ask at most one main direct question when a required item is missing;
- respond to urgent safety/medical content before normal intake progression;
- avoid exposing record field names or internal diagnostics to the user;
- use `intake_response` policy;
- stream through the gateway;
- do not generate a second hidden decision call.

### 11.9 Initial intake opening

The initial opening should use the same processor and prompt path. Do not retain a guest-user mini-workflow or infer identity from a placeholder user ID.

Profile creation is complete before entering `INTAKE`. The processor receives a valid profile and produces an opening response from explicit input.

## 12. Workstream F — `AssessmentProcessor`

### 12.1 Responsibility

`AssessmentProcessor` owns one background assessment operation that transforms the completed intake record/transcript and available style definitions into a typed assessment result.

It owns:

- concise case formulation;
- therapy-style scoring and rationale;
- key topic matching;
- initial plan material for style selection;
- validation that every selectable style has usable initial-plan material.

It does not own:

- style selection input parsing;
- user-facing continuation menus;
- database persistence;
- operation lifecycle;
- workflow transition;
- plan ID/version creation;
- calling `PostSessionProcessor` or a planning processor.

### 12.2 Target input

`AssessmentInput` should contain:

- validated completed intake record;
- intake transcript or a bounded canonical transcript representation;
- profile fields required for formulation;
- available `StyleDefinition` values.

Do not load anything from persistence inside the processor.

### 12.3 Target result

Use one serializable `AssessmentResult` that can be stored as the assessment operation result document.

Recommended shape:

```text
formulation
presenting_concerns
strengths_and_resources
risk_or_boundary_notes
style_recommendations[]
```

Each `StyleRecommendation` should contain:

```text
style_id
score
rationale
key_topics
initial_plan
```

Each `initial_plan` contains the target `Plan` content excluding application-assigned identity/lineage fields:

```text
focus
themes
goals
current_progress
planned_interventions
revision_recommendations
```

The selected style is not persisted into a plan during assessment. On `select_style`, Phase 4 selects the matching recommendation, combines its initial-plan material with the explicit selected style, and commits the first immutable plan.

This guarantees that style selection requires no additional LLM call and remains an atomic command.

### 12.4 Combined assessment call

Prefer one structured `assessment` call over one call per style plus a later planning call.

The combined prompt should include:

- compact intake summary/transcript;
- all available style IDs, descriptions, and concise assessment instructions;
- scoring scale and ranking rules;
- requirement to return one recommendation and plan material for every selectable style;
- instruction to remain grounded in intake evidence;
- complete `AssessmentResult` schema.

Reasons:

- fewer local-model calls;
- lower latency and heat;
- one coherent formulation;
- no shared mutable results dictionary;
- no concurrency-order problem;
- no nested planning agent;
- direct operation result persistence.

If optional local-model smoke testing demonstrates that the combined schema is unreliable, the fallback design is a bounded `asyncio.TaskGroup` of one structured style call per definition plus one pure aggregation step. Such a change requires measured evidence and must not reintroduce agent objects.

### 12.5 Validation and normalization

After structured generation:

- require exactly one entry per available style;
- reject unknown or duplicate style IDs;
- enforce score bounds;
- enforce non-empty rationale and plan essentials;
- sort recommendations deterministically by descending score and stable style order;
- ensure at least one plan goal and intervention;
- normalize whitespace and deduplicate short lists deterministically;
- do not silently invent a conservative fallback recommendation after a failed model call.

A structurally invalid result follows the gateway correction path and then fails the assessment operation if still invalid.

### 12.6 Removed legacy behavior

Do not port:

- scanning recent assistant text for recommendation signatures;
- parsing natural-language style selection;
- continuation-choice menus;
- `await_selection` action strings;
- per-style writes to a shared dict under a Trio nursery;
- RAG retrieval;
- `reflection_agent.create_initial_plan_with_style(...)`;
- generic `StructuredTherapyPlanOutput` compatibility builders.

Style selection becomes a typed command in Phase 4/5.

## 13. Workstream G — `TherapyProcessor`

### 13.1 Responsibility

`TherapyProcessor` owns therapy message construction and model streaming for an active therapy session.

It owns:

- therapy-style system instructions;
- opening versus continuation prompt composition;
- use of profile, current plan, session briefing, and recent transcript context;
- deterministic context bounding;
- one streaming response call per accepted chat turn.

It does not own:

- session lookup;
- current plan lookup;
- session timing;
- extension decisions;
- workflow navigation;
- message persistence;
- chat-turn lifecycle;
- previous-session database queries;
- RAG retrieval;
- post-session processing;
- closing the session.

### 13.2 Target input

Define `TherapyTurnInput` with:

- editable profile summary needed for respectful address/language;
- backend-owned derived profile document or a compact validated view;
- current immutable plan;
- optional latest session briefing;
- optional recent session summaries supplied by the application;
- ordered active-session transcript;
- latest user message, or explicit opening-turn marker;
- selected `StyleDefinition`;
- context-limit configuration.

Do not pass a database or mutable global user context.

### 13.3 Processor interface

Illustrative interface:

```python
class TherapyProcessor:
    def build_messages(self, input: TherapyTurnInput) -> list[ChatMessage]: ...

    def stream_response(
        self,
        input: TherapyTurnInput,
    ) -> AsyncIterator[str]: ...
```

`stream_response` may call `build_messages` internally. Keeping `build_messages` public or module-level makes prompt composition directly testable without a model call.

### 13.4 Context construction

Implement one deterministic `TherapyContextBuilder` or pure helper.

Context priority:

1. safety and role instructions;
2. selected therapy-style instructions;
3. current plan focus/goals/interventions;
4. current patient message;
5. recent active-session turns;
6. latest session briefing;
7. compact derived profile/recent-session context.

Use simple configurable limits such as:

- maximum active-session messages;
- maximum characters per section;
- maximum total context characters.

Do not add a tokenizer dependency in Phase 3. Truncation must be deterministic, preserve the newest dialogue, and never truncate the current user message silently.

### 13.5 Opening turn

Opening behavior should use explicit input, not inference from an empty message combined with database history.

For the first therapy session:

- acknowledge the plan focus without presenting it as a diagnosis;
- invite the user to choose what feels most important;
- use the selected style naturally.

For later sessions:

- use the latest validated briefing;
- mention continuity selectively;
- avoid claiming memory not represented in supplied context.

The processor does not determine whether a briefing is stale by reading the clock. Phase 4 supplies a briefing accepted by application policy, or no briefing.

### 13.6 Continuation turns

Use one `therapy_response` stream call. The system instruction should require:

- direct engagement with the latest user message;
- concise but therapeutically useful responses;
- limited questions rather than question lists;
- style consistency;
- no fabricated biographical memory;
- explicit handling of urgent safety statements;
- no discussion of internal plans, scores, or system prompts.

### 13.7 Removed legacy behavior

Do not port:

- database fallback when no plan is in context;
- RAG retrieval;
- style-service calls during each turn;
- `BriefingStatus` clock logic inside the processor;
- deep-topic detection as a second LLM call;
- session-extension workflow;
- `next_action` and workflow events;
- therapist-to-reflection dependency;
- processor-generated persistence fallback text.

The target workflow contains no session-extension command. Reintroducing extension requires a separate product decision and contract change, not an implicit Phase 3 compatibility feature.

## 14. Workstream H — `PostSessionProcessor`

### 14.1 Responsibility

`PostSessionProcessor` consolidates the useful behavior currently distributed across reflection, note-taking, memory, planning, and enrichment components.

It owns:

- analysis of the completed session;
- compact session summary;
- next-session briefing;
- backend-owned derived-profile patch;
- immutable plan revision patch or explicit no-op;
- patient-grounded intervention evidence;
- typed validation and deterministic patch normalization.

It does not own:

- reading prior sessions or the current plan from SQLite;
- operation lifecycle;
- session finalization;
- plan version/ID creation;
- profile or plan persistence;
- stage transition;
- retry scheduling;
- cross-session caches;
- calling other processors.

### 14.2 Target input

`PostSessionInput` should contain everything required for one deterministic attempt:

- completed therapy session and transcript;
- current immutable plan used by the session;
- editable profile fields needed for context;
- current backend-owned derived-profile document;
- optional prior session briefing;
- bounded recent session summaries or derived context;
- selected style definition.

Phase 4 loads this context before starting the operation. The processor performs no storage calls.

### 14.3 Two-call design

Use at most two structured calls:

1. `post_session_analysis` converts the transcript into a compact validated `SessionAnalysisResult`.
2. `post_session_update` converts that analysis plus current profile/plan context into a validated `PostSessionResult`.

This design intentionally replaces the legacy cascade of session enrichment, memory analysis, plan reflection, tier change detection, tier updates, and briefing generation.

Benefits:

- the full transcript is analyzed once;
- the second call receives compact structured context;
- schemas remain smaller than one monolithic all-purpose output;
- retries rerun a clearly bounded operation;
- tests can isolate analysis from patch generation;
- there is no nested agent graph.

Do not exceed two model calls without measured evidence and an explicit update to this plan.

### 14.4 Session analysis result

Recommended fields:

```text
summary
key_themes
dominant_affects
important_moments
patient_insights
progress_indicators
unresolved_topics
interventions_and_responses
safety_or_boundary_notes
```

Intervention evidence should distinguish:

- proposed;
- accepted;
- completed.

Claims should be grounded in patient turns where possible. Do not infer completion merely because the assistant suggested an exercise.

### 14.5 Post-session result

Recommended fields:

```text
session_summary
session_briefing
derived_profile_patch
plan_patch
```

`session_briefing` should be a compact typed model containing:

- narrative handoff;
- continuity points;
- unresolved issues;
- recommended opening focus;
- things to avoid;
- relevant emotional/theme context;
- patient-grounded intervention evidence.

Do not retain legacy fields solely because they existed in the old briefing schema. Keep only information used by the next therapy prompt or meaningful history display.

### 14.6 Derived-profile patch

The derived profile is backend-owned and separate from editable profile fields.

Patch requirements:

- include only changed or newly supported observations;
- distinguish patient-stated facts from interpretive hypotheses;
- avoid rewriting the entire document on every session;
- preserve existing information not addressed by the patch;
- never change editable name, language, or date-of-birth fields;
- use pure deterministic merge logic;
- make no-op detection explicit.

The exact derived-profile schema should remain compact and aligned with the Phase 2 JSON seam. Do not recreate Tier 1/Tier 3 labels as architecture concepts.

### 14.7 Plan patch

Use a patch model aligned with mutable content of a future immutable plan revision:

- focus;
- themes;
- goals;
- current progress;
- planned interventions;
- revision recommendations.

Rules:

- selected style is unchanged by post-session processing;
- lineage, IDs, version, timestamps, and source session are assigned by the application/store;
- an empty/no-op patch means no new plan revision;
- a patch must not remove all goals or interventions;
- deterministic merge produces complete candidate plan content;
- compare normalized candidate content with the current plan to decide whether a revision is required.

Do not ask the LLM to output `plan_revision_required` as an authoritative boolean. Derive it from the validated patch and normalized current plan.

### 14.8 Failure semantics

If either structured call fails:

- propagate the stable gateway error;
- do not return partial `PostSessionResult`;
- do not silently preserve a successful analysis as operation completion;
- let Phase 4 mark the operation failed and retry the same operation row.

Phase 4 may choose to persist intermediate diagnostics in traces, but the Phase 3 processor contract is all-or-failure.

### 14.9 Removed legacy behavior

Do not port:

- `TrioReflectionAgent` coordination methods;
- `TrioMemoryAgent` caches and cross-session database scans;
- `TrioPlanningAgent` mutable strategy/evolution state;
- Tier 2/Tier 3 worker/job concepts;
- on-demand enrichment of prior sessions;
- RAG retrieval;
- health checks per agent;
- generic reflection summary text as a workflow response;
- `AgentResponse` metadata carrying plan/profile/session updates;
- cancellation shielding inside processors.

Post-session processing is a background application operation, not a conversational agent turn.

## 15. Workstream I — Prompt design and context discipline

### 15.1 Message separation

Build prompts as `Sequence[ChatMessage]`, not as one interpolated provider-specific prompt string.

Use:

- system messages for stable role, safety, style, and output instructions;
- user messages for bounded supplied context and the current task;
- assistant messages only when representing actual conversation history.

Do not inject stored assistant/user transcript text into the system instruction.

### 15.2 Delimit supplied documents

Clearly delimit:

- profile summary;
- intake record;
- plan;
- session briefing;
- transcript;
- style definitions.

Treat stored/user-provided content as data, not instructions. Include a stable instruction to ignore instructions embedded in supplied records or transcripts.

### 15.3 Prompt reuse

Reuse pure formatting helpers where the same domain document appears in multiple phases, but do not introduce a generic template engine.

Appropriate shared helpers:

- message transcript formatting;
- compact plan formatting;
- bounded JSON/document formatting;
- style definition formatting.

Inappropriate shared abstractions:

- universal agent prompt builder;
- arbitrary template registry;
- runtime prompt plugin discovery;
- Jinja dependency for static Python-owned prompts.

### 15.4 Prompt version observability

A small constant per major prompt, such as `PROMPT_VERSION = "assessment-v1"`, is acceptable when it is logged by the tracing context and helps compare probe runs.

Do not persist prompt versions into domain entities or API contracts.

### 15.5 Testing prompts

Tests should assert:

- required system instructions are present;
- current user content is included exactly once;
- forbidden internal fields are absent;
- context truncation preserves required priority sections;
- style instructions are selected correctly;
- output schema/task is correct.

Avoid full prompt snapshots for every wording change. Use small snapshots only for stable structured schema instructions where exact formatting matters.

## 16. Workstream J — Configuration

### 16.1 Phase 3 configuration surface

Define only configuration needed to construct policies and the concrete adapter:

- base URL;
- API key;
- default model;
- optional per-task model overrides;
- task temperatures;
- task timeouts;
- task structured-output modes;
- optional default/per-task request extras;
- diagnostic prompt logging flags and bounds.

Do not add:

- provider selection enum;
- multiple API-key lists;
- requests-per-minute settings;
- burst capacity;
- agent-specific service settings;
- RAG settings;
- cloud-provider schema capability inference.

### 16.2 Validation

Configuration should fail fast when:

- model is empty;
- base URL is malformed;
- timeout is non-positive;
- temperature is outside accepted bounds;
- structured mode is unknown;
- request-extra JSON is invalid;
- a required task policy is missing.

Policy construction should be a pure function with unit tests.

### 16.3 Legacy environment variables

Phase 3 does not remove legacy environment variables because the old runtime still runs. New target settings may coexist temporarily but must not be wired into the legacy container.

Phase 6/7 will delete or rename obsolete settings after cutover.

## 17. Legacy component treatment inventory

| Legacy component/concept | Phase 3 treatment | Final deletion phase |
|---|---|---|
| `services/llm_service.py` | Reimplement only required streaming, structured validation, and diagnostics behind target gateway | Phase 6 |
| LangChain message/provider classes | Do not port | Phase 6 dependency cleanup |
| Gemini/Ollama/provider branches | Do not port | Phase 6/7 |
| `TrioRateLimiter` | Do not port | Phase 6 |
| API-key rotation | Do not port | Phase 6 |
| `services/llm_phases.py` fine-grained phases | Replace with compact semantic `LLMTask` | Phase 6 |
| `TrioIntakeAgent` | Replace behavior with `IntakeProcessor` | Phase 6 |
| intake record merge/completeness/evidence helpers | Port useful pure logic to target intake package | Legacy copies deleted Phase 6 |
| `NoteTakerAgent.extract_intake_patch` | Fold into intake processor/helper | Phase 6 |
| `TrioAssessmentAgent` | Replace with one typed assessment operation | Phase 6 |
| natural-language style selection parsing | Do not port; explicit API command later | Phase 6 |
| assessment shared-dict concurrency | Replace with one combined structured result | Phase 6 |
| planning agent initial-plan creation | Fold initial plan material into assessment result | Phase 6 |
| `StyleService` | Replace with immutable style catalog/resource loader | Phase 6 |
| style `knowledge.md` retrieval | Do not port | Phase 6 or leave inert asset until reviewed |
| `TrioTherapistAgent` | Replace with `TherapyProcessor` | Phase 6 |
| therapist DB fallback/context queries | Application supplies context; do not port | Phase 6 |
| deep-topic detection | Do not port without a target workflow decision | Phase 6 |
| session extension workflow | Do not port | Phase 6 |
| `TrioReflectionAgent` | Consolidate into `PostSessionProcessor` | Phase 6 |
| `TrioMemoryAgent` | Replace with explicit input context and post-session analysis | Phase 6 |
| `TrioPlanningAgent` | Replace with assessment initial-plan material and post-session plan patch | Phase 6 |
| note-taker session summary/briefing | Fold into post-session outputs | Phase 6 |
| Tier 1/2/3/4 orchestration labels | Collapse into derived profile, session summary/briefing, and plan concepts | Phase 6 |
| no-op RAG service | Do not import or replace | Phase 6 |
| `AgentResponse` | Never use in target package | Phase 6 |
| generic output validators/builders | Replace with direct target Pydantic validation | Phase 6 |
| agent health checks | Replace later with API/gateway health only | Phase 5/6 |

## 18. Testing strategy

### 18.1 Test layers

Phase 3 should use four layers:

1. pure model/policy/helper unit tests;
2. concrete gateway tests against mocked HTTP transport;
3. processor tests using `FakeLLM`;
4. optional real local-server smoke tests.

No Phase 3 CI test should require a real model server.

### 18.2 Gateway contract tests

Test:

- project message conversion;
- streaming chunk extraction;
- empty/control chunk filtering;
- no buffering before first yield;
- cancellation propagation;
- timeout classification;
- connection/5xx classification;
- JSON schema request construction;
- JSON object request construction;
- prompt-constrained request construction;
- Pydantic validation;
- Markdown fence normalization;
- one correction attempt;
- failure after the correction attempt;
- empty response handling;
- SDK retries disabled;
- adapter request extras merged correctly;
- secrets and prompts redacted in default logs.

Prefer `httpx.MockTransport` injected into the OpenAI async client or an equivalent in-process transport. Do not mock private SDK internals or depend on a real network port.

### 18.3 Fake gateway tests

Test:

- ordered expectation consumption;
- task mismatch failure;
- output-model mismatch failure;
- scripted chunk streaming;
- scripted typed errors;
- mid-stream failure;
- remaining-expectation assertion;
- returned model isolation from mutation.

### 18.4 Intake tests

Port or recreate behavior-focused coverage for:

- extraction prompt grounding;
- valid patch application;
- invalid evidence rejection;
- assistant-authored evidence rejection;
- strict quote validation;
- empty patch;
- no-op merge;
- repeated merge idempotency;
- completion matrix;
- unknown/declined answers;
- risk-screen requirement;
- max-turn failure safeguard;
- next missing item selection;
- opening turn;
- direct-ask response plan;
- closing response plan;
- processor error propagation;
- no persistence/API/workflow imports.

### 18.5 Assessment tests

Test:

- all available styles included in the prompt;
- exactly one result per style;
- duplicate/unknown/missing style rejection;
- deterministic recommendation order;
- score bounds;
- plan material completeness;
- no selected plan persisted by processor;
- no natural-language selection parsing;
- one structured LLM call in the normal path;
- gateway failure propagation.

### 18.6 Therapy tests

Test:

- first-session opening message construction;
- resumed-session briefing construction;
- selected style instructions;
- plan context inclusion;
- current user message preserved;
- recent message ordering;
- deterministic context truncation;
- no database/RAG access;
- one streaming call;
- chunks passed through unchanged;
- mid-stream failure propagation;
- no workflow/session-extension decision.

### 18.7 Post-session tests

Test:

- exactly two structured calls in the normal path;
- transcript supplied only to the analysis call;
- compact analysis supplied to update call;
- session analysis validation;
- patient-grounded intervention evidence;
- derived-profile patch merge;
- editable profile fields cannot be patched;
- plan patch merge;
- plan no-op detection;
- plan revision candidate completeness;
- selected style preserved;
- first-call failure stops processing;
- second-call failure returns no partial result;
- no database/process/application imports.

### 18.8 Processor integration scenario

Add one small `tests/integration/jung/test_phase_processors.py` scenario using only target domain models and `FakeLLM`:

1. prepare and stream an intake turn;
2. produce a completed intake result;
3. run assessment and obtain style-specific initial-plan material;
4. build and stream a therapy opening and response;
5. run post-session analysis/update;
6. validate that outputs are serializable and compatible with Phase 2 document/plan seams.

This is not a workflow test and must not implement a miniature `TherapyApplication`.

### 18.9 Legacy test treatment

Classify existing agent/LLM tests into:

- behavior to port to target tests;
- legacy-only implementation tests retained until Phase 6;
- tests for behavior intentionally removed;
- duplicate tests that can be deleted at cutover.

Do not delete legacy tests in Phase 3 unless they are already unrelated to the running path and an accepted inventory marks them removable.

## 19. Import and architecture rules

Add Phase 3 validation enforcing:

### 19.1 LLM package

`src/jung/llm` may import:

- standard library;
- Pydantic;
- OpenAI SDK;
- project-owned domain/error/config types.

It must not import:

- legacy `psychoanalyst_app` runtime modules;
- Trio;
- LangChain;
- database code;
- API/client code;
- phase processors.

### 19.2 Processor packages

`src/jung/phases` may import:

- target domain models;
- project-owned gateway contracts;
- pure style definitions;
- same-phase helpers.

They must not import:

- OpenAI SDK;
- LangChain;
- Trio;
- SQLite/store modules;
- API or client modules;
- application/composition modules;
- legacy orchestration/container/services;
- another top-level phase processor.

A processor may call pure shared formatting or merge helpers. It may not construct or invoke another processor.

### 19.3 Forbidden concepts

Fail validation if target processor code introduces:

- `AgentResponse`;
- `next_action`;
- `WorkflowEvent`;
- `user_id`;
- service-container string lookups;
- RAG/retriever imports;
- generic agent base classes;
- database calls.

Use AST/import checks rather than line-count budgets.

## 20. Implementation sequence

Workstreams use internal names (Step 0, Workstreams A–D) to avoid confusion with architecture-refactor Phases 1–7.

### Step 0 — Persistence seam remediation

Before gateway or processor code:

- add domain `PlanContent` with shared validators; refactor `Plan` to inherit it;
- refactor `select_style_and_create_initial_plan(content=PlanContent)`;
- add `sessions.intake_record_json` in fresh `CREATE TABLE` (schema version 3);
- extend `complete_chat_turn(..., intake_record=None)` for intake sessions;
- refactor `complete_post_session(..., new_plan: NewPlanRevision | None)` with store-derived compact operation result;
- add five integration tests for intake and post-session seams;
- scope `validate-refactor-phase-2` pytest and ruff to Phase 2 paths only.

Validation: `make validate-refactor-phase-2` green.

### Step 1 — Confirm Phase 2 seams

Before writing model-facing code:

- inspect final Phase 2 domain models and error types;
- confirm how intake/assessment/post-session documents are represented at the store boundary;
- confirm plan content fields and patch merge expectations;
- confirm message IDs/sequences available for evidence references;
- record any mismatch as a Phase 2 defect rather than working around it in processors.

Validation:

- no persistence redesign;
- no compatibility model introduced;
- Phase 2 tests remain green.

### Step 2 — Add gateway contracts and policies

Implement:

- `ChatRole`;
- `ChatMessage`;
- `LLMTask`;
- `StructuredOutputMode`;
- `ModelPolicy`;
- `LLMGateway`.

Add model/policy validation tests.

Validation:

- no provider imports in `gateway.py`;
- no legacy task names;
- policy construction is deterministic.

### Step 3 — Add `FakeLLM`

Implement the strict scripted fake before processors.

Validation:

- protocol conformance;
- expectation mismatch tests;
- stream and structured scenarios;
- no network or sleeps.

### Step 4 — Implement structured-output helpers

Implement:

- schema request construction;
- prompt schema instruction;
- response text normalization;
- Pydantic validation;
- concise validation-error formatting;
- one correction attempt.

Validation:

- all three modes tested;
- no JSON-repair dependency;
- exactly two attempts maximum.

### Step 5 — Implement `OpenAICompatibleLLM`

Implement async streaming, structured generation, error classification, adapter extras, and lifecycle ownership.

Validation:

- mocked HTTP transport tests;
- no Trio/thread bridge;
- no LangChain;
- SDK retries disabled;
- cancellation preserved.

### Step 6 — Implement tracing decorator

Add boundary tracing and redaction behavior.

Validation:

- stream remains lazy;
- default logs contain no full prompt/response;
- failure/cancellation classification remains unchanged.

### Step 7 — Implement style catalog

Port only required style assets and add pure loader validation.

Validation:

- deterministic order;
- missing/duplicate asset failure;
- no RAG/service state.

### Step 8 — Implement intake models and pure policy

Port/simplify intake record, evidence, merge, completeness, and next-item policy before adding LLM calls.

Validation:

- pure unit tests;
- idempotent merge;
- max-turn failure safeguard;
- no legacy context types.

### Step 9 — Implement `IntakeProcessor`

Add patch extraction, turn preparation, prompt composition, and streaming.

Validation:

- strict `FakeLLM` expectations;
- one extraction call and one response stream in normal non-opening turns;
- typed turn plan;
- no state transition/persistence.

### Step 10 — Implement `AssessmentProcessor`

Add combined assessment schema, prompt, validation, deterministic ordering, and per-style initial-plan material.

Validation:

- one structured call;
- complete result for every style;
- no selection parsing or nested planning object.

### Step 11 — Implement `TherapyProcessor`

Add context builder, opening/continuation prompt composition, and one streaming call.

Validation:

- deterministic context bounds;
- no DB/RAG/time/workflow behavior;
- chunks unchanged.

### Step 12 — Implement `PostSessionProcessor`

Add session analysis, update generation, pure derived-profile merge, pure plan merge, and no-op detection.

Validation:

- two structured calls maximum;
- no partial success;
- typed serializable result;
- no nested agents.

### Step 13 — Add processor integration scenario

Exercise all processors with Phase 2 models and `FakeLLM` without building the application layer.

Validation:

- result documents serialize and revalidate;
- processor outputs align with store completion inputs expected by Phase 4;
- no database opened.

### Step 14 — Add Phase 3 validation target

Add or extend:

```text
phase-3-test
validate-refactor-phase-3
```

Recommended composition:

```text
phase-3-test:
  gateway/model/helper unit tests
  processor unit tests
  processor integration scenario

validate-refactor-phase-3:
  lint/type checks for target LLM and phase packages
  import/forbidden-concept checks
  phase-3-test
```

Do not duplicate the complete repository finalization suite inside the target.

### Step 15 — Review and handoff

Update:

- deletion inventory with concrete replacements;
- test-treatment inventory;
- baseline metrics for new package/tests;
- Phase 3 exit checklist;
- direct dependency declarations for the OpenAI SDK.

Do not mark legacy agents or services deleted yet.

## 21. Suggested commit structure

Keep commits narrow, reviewable, and green.

### Commit 1

```text
feat(llm): add target gateway contracts and deterministic fake
```

Includes:

- messages/tasks/policies;
- gateway protocol;
- fake LLM;
- unit tests.

### Commit 2

```text
feat(llm): add async OpenAI-compatible gateway
```

Includes:

- structured helpers;
- concrete adapter;
- error classification;
- mocked transport tests.

### Commit 3

```text
feat(llm): add target LLM tracing and policy configuration
```

Includes:

- tracing decorator;
- redaction;
- task policy construction;
- tests.

### Commit 4

```text
feat(phases): add style catalog and intake processor
```

Includes:

- style definitions/loader;
- intake models;
- merge/completeness policy;
- intake processor and tests.

### Commit 5

```text
feat(phases): add assessment and therapy processors
```

Includes:

- assessment result and prompts;
- assessment processor;
- therapy context/prompts/processor;
- tests.

### Commit 6

```text
feat(phases): add consolidated post-session processor
```

Includes:

- analysis/update models;
- profile/plan patch merge;
- post-session processor;
- tests.

### Commit 7

```text
test(refactor): add Phase 3 integration and architecture validation
```

Includes:

- processor integration scenario;
- import checks;
- Make/CI targets;
- inventory and metric updates.

Fewer commits are acceptable if each commit remains coherent. Do not split every prompt or model into a separate commit.

## 22. CI and local validation

### 22.1 Fast local loop

Recommended:

```bash
uv run pytest tests/unit/jung/llm tests/unit/jung/phases -q
uv run pytest tests/integration/jung/test_phase_processors.py -q
uv run ruff check src/jung/llm src/jung/phases src/jung/styles.py tests/unit/jung tests/integration/jung
```

Use the repository's canonical type-check command once Phase 2 has established the target package configuration.

### 22.2 PR validation

The Phase 3 PR should run:

1. standard repository finalization once;
2. Phase 3 import/forbidden-concept validation;
3. Phase 3 gateway and processor tests;
4. Phase 2 target-core tests;
5. Phase 1 characterization smoke proving the legacy runtime was not disturbed.

Do not run a real local model in mandatory hosted CI.

### 22.3 Local-model smoke (required before merge)

Add one opt-in command:

```text
make smoke-refactor-phase-3-local-llm
```

Run this against the target local server before merging Phase 3. It remains manual and is not part of mandatory hosted CI.

Required environment variables (fail fast when missing or empty):

- `PHASE3_SMOKE_SERVER` — implementation identity (for example `llama.cpp`), not the HTTP endpoint
- `PHASE3_SMOKE_BASE_URL` — OpenAI-compatible base URL
- `PHASE3_SMOKE_MODEL` — exact model identifier loaded on the server

**Request timeout vs path acceptance budget**

- `PHASE3_SMOKE_REQUEST_TIMEOUT` (fallback: `PHASE3_SMOKE_TIMEOUT`) — per provider attempt
- `PHASE3_SMOKE_THERAPY_MAX_SECONDS`, `PHASE3_SMOKE_ASSESSMENT_MAX_SECONDS`, `PHASE3_SMOKE_POST_SESSION_MAX_SECONDS` — end-to-end path budgets (default 300 each)
- `PHASE3_SMOKE_STRICT_ACCEPTANCE=1` (default) — enforces aggregate `asyncio.timeout` per path; merge gate
- `PHASE3_SMOKE_STRICT_ACCEPTANCE=0` — diagnostic mode; records `acceptance_passed` without enforcing aggregate deadline

When request timeout and path budget are both 300 seconds, aggregate cancellation may appear as `path_timeout` / `cancelled` rather than provider `timeout`. For attribution, use `REQUEST_TIMEOUT > path_budget` in diagnostic mode.

**Representative merge acceptance**

Merge acceptance must use the intended deployment model, structured mode, thinking configuration, request extras, and completion-token policies. Smoke-only caps from `PHASE3_SMOKE_MAX_COMPLETION_TOKENS` diagnose timeouts but cannot satisfy the acceptance gate unless equivalent runtime policy is adopted.

Merge acceptance example:

```bash
# structured mode, extras, thinking, and token caps must match intended runtime.
PHASE3_SMOKE_REQUEST_TIMEOUT=300 \
PHASE3_SMOKE_STRICT_ACCEPTANCE=1 \
PHASE3_SMOKE_STRUCTURED_MODE=json_schema \
make smoke-refactor-phase-3-local-llm
```

Diagnostic example (focused post-session, experimental caps):

```bash
PHASE3_SMOKE_TARGET="tests/smoke/jung/test_phase3_local_llm.py::test_smoke_post_session_processor" \
PHASE3_SMOKE_PYTEST_ARGS="-vv -s --log-cli-level=INFO --durations=0" \
PHASE3_SMOKE_LOG_PROMPT_PREVIEWS=0 \
PHASE3_SMOKE_REQUEST_TIMEOUT=360 \
PHASE3_SMOKE_STRICT_ACCEPTANCE=0 \
PHASE3_SMOKE_MAX_COMPLETION_TOKENS='{"post_session_analysis":1400,"post_session_update":1800}' \
PHASE3_SMOKE_SERVER=llama.cpp \
PHASE3_SMOKE_BASE_URL=http://host.docker.internal:8080/v1 \
PHASE3_SMOKE_MODEL='<exact-model-id>' \
make smoke-refactor-phase-3-local-llm
```

A `PHASE3_SMOKE_TIMEOUT=900` rerun is diagnostic only and is not representative performance evidence. Do not merge on 900-second diagnostic success alone.

It should verify:

- one short therapy stream via `TherapyProcessor.stream_response()`;
- one full `AssessmentProcessor.assess()` call with real prompts and styles;
- one full two-call `PostSessionProcessor.process()` flow;
- configured structured-output mode;
- configured request extras such as thinking-mode controls;
- `gateway.aclose()` cleanup;
- structured-call and provider-attempt evidence with `call_id` correlation;
- path status, acceptance fields, and instrumentation integrity;
- llama.cpp or LM Studio compatibility through the same adapter.

The smoke test must not mutate the database or require the legacy server.
Emit one machine-extractable terminal line when real smoke metadata is present (`server`, `model`, `base_url`):

```text
PHASE3_SMOKE_EVIDENCE={"server":"llama.cpp","strict_acceptance":true,"calls":[...],"provider_attempts":[...],...}
```

Synthetic diagnostic unit tests must not emit this line. Use `PHASE3_SMOKE_PYTEST_ARGS="-vv -s --log-cli-level=INFO --durations=0"` for progress visibility via provider-attempt and tracing logs.

Evidence layers:

- **path** (`therapy`, `assessment`, `post_session`) — `status`, `acceptance_passed`, latency
- **calls** — structured logical calls (`input_chars`, `output_schema_chars`, `result_chars`)
- **provider_attempts** — per structured-output request (`prompt_chars`, `correction_trigger`, token usage when available)

Record a PR evidence table with server implementation, base URL, model, structured mode, path budgets, request timeout, effective completion caps, measured latencies, and configured nonsecret extras. Do not record therapeutic content.

### 22.4 Dependency validation

Declare `openai` as a direct project dependency if it is not already direct. Do not rely on a transitive LangChain dependency.

Do not remove LangChain or legacy provider packages until the old runtime is deleted in Phase 6/7.

Do not add:

- `tenacity`;
- JSON repair packages;
- tokenizer packages;
- prompt-template frameworks;
- provider SDKs beyond the direct OpenAI-compatible client.

## 23. Risk register

### Risk: useful therapeutic behavior is lost during consolidation

Mitigation:

- port behavior-focused tests before deleting legacy code;
- map every legacy agent responsibility explicitly;
- retain intake evidence policy, style instructions, continuity briefing, and plan/profile update semantics;
- gate cutover later with deterministic workflow probes.

### Risk: the combined assessment schema is unreliable on smaller local models

Mitigation:

- keep the schema bounded;
- use one correction attempt;
- validate with the intended local model in the opt-in smoke;
- fall back only to per-style structured calls with measured evidence, not pre-emptively.

### Risk: post-session output becomes too large or brittle

Mitigation:

- use two calls with a compact intermediate analysis;
- keep the second schema focused on briefing and patches;
- remove legacy tier fields not used by the target product;
- bound lists and narrative fields.

### Risk: provider capability differences leak into processors

Mitigation:

- explicit structured-output mode in policy;
- request extras in adapter configuration;
- only `llm/` imports the SDK;
- local smoke covers target servers.

### Risk: fake tests pass while real prompt construction is incorrect

Mitigation:

- strict expected task/output type;
- message predicates asserting semantic prompt content;
- concrete adapter request tests;
- optional local smoke;
- later deterministic application probe.

### Risk: processor interfaces accidentally perform Phase 4 orchestration

Mitigation:

- no store/application/API imports;
- typed inputs contain all required context;
- typed outputs describe results, not mutations;
- import/forbidden-concept checks;
- no workflow stage or revision fields in processor contracts.

### Risk: context growth degrades local-model performance

Mitigation:

- deterministic character/message budgets;
- compact briefings and summaries;
- transcript analyzed once in post-session;
- no repeated cross-session scans inside processors;
- measure prompt sizes in traces.

### Risk: hidden retries duplicate latency and heat

Mitigation:

- SDK retries disabled;
- exactly one explicit structured correction;
- no automatic text-stream retry;
- Phase 4 owns operation retry.

### Risk: temporary duplication persists too long

Mitigation:

- target code never wraps legacy code;
- update deletion inventory with exact replacements;
- no production dual mode;
- Phase 6 removes the old agent/LLM stack after API cutover.

## 24. Review checklist

### Architecture

- [ ] Only `src/jung/llm` imports the OpenAI SDK.
- [ ] No target code imports LangChain or Trio.
- [ ] New processors use final names and target models.
- [ ] No processor imports persistence, API, client, application, or legacy runtime modules.
- [ ] No processor constructs or calls another processor.
- [ ] No agent base class, factory, registry, or service locator is introduced.
- [ ] No RAG abstraction is introduced.
- [ ] New code remains unused by the running legacy path.

### LLM boundary

- [ ] One gateway protocol exposes only streaming text and structured generation.
- [ ] One concrete async OpenAI-compatible adapter exists.
- [ ] One gateway instance can serve all task policies.
- [ ] SDK retries are disabled.
- [ ] Structured mode is policy/configuration-driven.
- [ ] Structured output receives at most one correction attempt.
- [ ] Provider failures map to stable target errors.
- [ ] Cancellation is not shielded or swallowed.
- [ ] Provider objects do not escape the adapter.
- [ ] Default tracing redacts prompt and response content.

### Fake and tests

- [ ] `FakeLLM` implements the exact gateway protocol.
- [ ] Expectations are strict and ordered.
- [ ] Processor tests use typed fake results.
- [ ] Concrete parsing/correction is tested at the adapter layer.
- [ ] No mandatory test requires a model server.
- [ ] Tests assert behavior and invariants rather than private call choreography.

### Styles

- [ ] Style definitions are immutable and loaded deterministically.
- [ ] Missing/duplicate assets fail clearly.
- [ ] No knowledge retrieval is required.
- [ ] Style selection parsing is absent.

### Intake

- [ ] Intake patch extraction is structured and grounded.
- [ ] Evidence merge is pure and idempotent.
- [ ] Completion is deterministic, not model-decided.
- [ ] Failed extraction cannot falsely complete a stale record.
- [ ] Response preparation returns a typed plan.
- [ ] Processor does not persist or transition workflow.

### Assessment

- [ ] Assessment result covers every selectable style.
- [ ] Every style has initial-plan material.
- [ ] Normal path uses one structured call.
- [ ] Selection requires no LLM call.
- [ ] No natural-language selection menu/parser remains.

### Therapy

- [ ] Context input is explicit and database-free.
- [ ] Context limits are deterministic.
- [ ] Opening and continuation behavior are testable without an LLM.
- [ ] One accepted turn maps to one text stream.
- [ ] No deep-topic, extension, workflow, or post-session behavior remains.

### Post-session

- [ ] Normal path uses at most two structured calls.
- [ ] Full transcript is analyzed once.
- [ ] Profile and plan updates are patches.
- [ ] Editable profile fields cannot be patched.
- [ ] Plan revision need is derived deterministically.
- [ ] No partial success is returned after a failed call.
- [ ] No memory/planning/reflection agent objects remain in the target design.

## 25. Phase 3 exit criteria

All criteria are blocking:

- [ ] Project-owned `ChatMessage`, `LLMTask`, `StructuredOutputMode`, and `ModelPolicy` exist.
- [ ] `LLMGateway` matches the accepted two-method protocol.
- [ ] `OpenAICompatibleLLM` uses the async OpenAI SDK directly.
- [ ] No target code imports LangChain or Trio.
- [ ] Streaming is lazy, cancellation-aware, and does not buffer the full response.
- [ ] Structured generation supports `json_schema`, `json_object`, and `prompt` modes.
- [ ] Invalid structured output gets exactly one correction attempt.
- [ ] Stable LLM error classification is tested.
- [ ] SDK/provider objects do not cross the gateway boundary.
- [ ] `TracingLLMGateway` records task/latency/status with redacted content by default.
- [ ] `FakeLLM` is strict, deterministic, and used by all processor tests.
- [ ] Immutable therapy styles load through a pure target catalog.
- [ ] `IntakeProcessor` exposes typed turn preparation and streaming.
- [ ] Intake evidence merge and completion policy are deterministic and tested.
- [ ] `AssessmentProcessor` returns a typed result containing one recommendation and initial-plan material per selectable style.
- [ ] Assessment selection requires no model call.
- [ ] `TherapyProcessor` builds bounded context and performs one stream per turn.
- [ ] `TherapyProcessor` contains no DB, RAG, timing, extension, or workflow logic.
- [ ] `PostSessionProcessor` consolidates session analysis, briefing, derived-profile patch, and plan patch behavior.
- [ ] Post-session normal execution uses no more than two structured calls.
- [ ] Profile and plan patch merges are pure and tested.
- [ ] No processor imports another processor.
- [ ] No target processor returns `AgentResponse`, metadata dicts, next actions, or workflow events.
- [ ] No target processor accesses persistence, API, client, or application code.
- [ ] Phase 3 tests pass without HTTP, SQLite, or a real LLM.
- [ ] Phase 2 core tests remain green.
- [ ] Phase 1 characterization and existing deterministic legacy tests remain green.
- [ ] No production runtime behavior changed.

## 26. Definition of done

Phase 3 is done when a developer can implement Phase 4 `TherapyApplication` without deciding:

- how model messages are represented;
- how task-specific model policies are selected;
- how local OpenAI-compatible streaming works;
- how structured output modes differ;
- how invalid structured output is corrected and classified;
- how LLM calls are faked deterministically;
- how style assets are loaded;
- what each processor receives;
- what each processor returns;
- how intake evidence and completion are decided;
- how assessment produces selectable initial-plan material;
- how therapy context is bounded and streamed;
- how post-session analysis becomes a briefing, profile patch, and plan patch;
- which legacy agent behaviors are intentionally removed.

If Phase 4 still requires direct calls to legacy agents, database access from processors, a new agent registry, provider-specific branches in application code, or redesign of processor result schemas, Phase 3 is not complete.

## 27. Handoff to Phase 4

Phase 4 begins with:

- tested Phase 2 domain/workflow/store foundation;
- one tested `LLMGateway` and direct OpenAI-compatible adapter;
- one tested `FakeLLM`;
- one immutable style catalog;
- typed intake turn plans;
- typed assessment operation results containing initial-plan material;
- typed therapy streaming behavior;
- typed post-session operation results;
- stable LLM error taxonomy;
- no legacy dependency in the target core.

Phase 4 may then add:

- explicit typed composition;
- `TherapyApplication` use cases;
- application locks;
- task supervision;
- `EventStream`;
- chat-turn acceptance, streaming, completion, and failure lifecycle;
- assessment and post-session operation execution;
- atomic result persistence;
- startup recovery and retries;
- full application integration tests with the real `SQLiteStore` and `FakeLLM`.

Phase 4 must not reopen the gateway, processor, or result-model design without measured evidence and an accepted update to the relevant ADR or target architecture document.
