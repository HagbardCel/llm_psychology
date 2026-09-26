# Current implementation: evidence before redesign

## Scope and method

Implementation baseline: local `main` at **`bd9051d6305dd834eda3ccb8930e6edb85f0debd`**, measured on **2026-09-26** in B0. Revision history since the Phase-9 pin `73492a5b8052cb5fc2ea0a3d02ae0fd6d910f452`: `73492a5b..a468070` added only the seven `architecture-plan/*.md` files; `a468070..bd9051d` applied only the focused `run_local` test-harness warning correction in `tests/unit/test_local.py`. Production and eval Python under `src/jung` and `evals` remain identical to `73492a5b`. No patient database, `.env` secrets, raw patient trace, or simulation transcript was needed.

B0 measured pristine `main` at `a468070eef308e472970ef78cccf12fe04a5b1d2` before that correction. Project contract: `requires-python >=3.11` ([pyproject.toml](../pyproject.toml)); locked OpenAI SDK `2.45.0` ([uv.lock](../uv.lock)). B0 validation interpreter: `Python 3.12.13` (`uv run python -V` during the gate). Inventory command:

```bash
for area in src/jung tests evals; do
  files=$(git ls-files "$area" | grep '\.py$')
  count=$(printf '%s\n' "$files" | grep -c .)
  lines=$(printf '%s\n' "$files" | xargs wc -l | tail -1 | awk '{print $1}')
  printf '%s files=%s lines=%s\n' "$area" "$count" "$lines"
done
```

Pre-fix B0 measurement at `a468070`: `src/jung` 75 / 14,432; `tests` 118 / 29,695; `evals` 15 / 6,922 (comments and blank lines included). The focused warning fix added four net lines in `tests/unit/test_local.py` only. Pinned post-fix implementation baseline `bd9051d`: `src/jung` 75 / 14,432; `tests` 118 / **29,699**; `evals` 15 / 6,922. Absent Phase-10-only paths on this baseline: `evals/simulation/intake_forensics.py`, `evals/intake_risk_denial_evidence.py`, `evals/test_intake_clear_risk_denial.py`. Worktree provenance for the inventory correction is in [06-migration-plan.md](06-migration-plan.md).

The original inspection covered canonical docs, runtime flows, persistence, model/context boundaries, diagnostics, clients, and test/eval owners. This refresh compared main against that inspection, checked the complete production diff, and inspected main's changed prompt, diagnostics/eval owners, schema version, and tracked source inventory. Unchanged runtime-flow findings carry forward. This is architectural inspection, not a line-by-line security review. Relative source links name paths present on main; use the pinned SHA when the editing branch differs. The prior Phase-10 inspection remains in [the original planning commit](https://github.com/HagbardCel/llm_psychology/blob/632cdcbf36194f9090f0a1a061c0c5c0935cfa17/architecture-plan/01-current-state.md).

A count of tracked Python files at the pinned implementation baseline `bd9051d`, including comments and blank lines, found (pre-fix `a468070` used 29,695 test lines):

| Area | Files | Lines |
|---|---:|---:|
| Production `src/jung` | 75 | 14,432 |
| `tests` including manual smoke | 118 | 29,699 |
| `evals` | 15 | 6,922 |

Counts identify concentrations, not defects. A correctness test is not unnecessary merely because it is long.

## Phase-10 investigation: historical, not the implementation base

At the 2026-09-20 inspection, `fix/phase-10-intake-completion` at `301d8bb` is 12 commits ahead of main, with no commits behind. [PR #76](https://github.com/HagbardCel/llm_psychology/pull/76) was open and unmerged when checked. Its description labels the outcome “Defect verified / journey incomplete,” records the historical canary's `intake_turn_limit_exceeded`, and states that remediated-head focused live validation was not run. Do not describe it as a proven final intake architecture or a completed successful journey.

The branch adds a narrow denial-prompt improvement, `intake.turn.evaluated` diagnostics, a diagnostic sink protocol, and extensive extraction/evidence reconstruction. Its investigation exposed clear-denial failures, ambiguous attempt correlation, observed-versus-committed state, and primary/cleanup failure handling. Preserve those lessons and the recorded limits, but do not port the forensic engine merely to delete it. Main has neither `evals/simulation/intake_forensics.py` nor `evals/intake_risk_denial_evidence.py` / `evals/test_intake_clear_risk_denial.py`. Its existing diagnostic recorder and simulation audit still require R3/R4 simplification.

Implementation starts from main without requiring PR #76 to merge or close. Retain the existing Phase-10 history and private evidence. Planning documents can move independently; the narrow old-extractor prompt fix is not an automatic prerequisite. Historical evidence is not admission for the new schema. B0 closed with a fresh main measurement and a warning-free deterministic gate on `bd9051d`; see the B0 entry in [06-migration-plan.md](06-migration-plan.md).

## Runtime and ownership

```mermaid
flowchart LR
    Local["jung foreground launcher"] --> API["FastAPI + Uvicorn"]
    Local --> Console["jung-console"]
    Console -->|"HTTP /api/v1; NDJSON chat"| API
    API --> App[TherapyApplication]
    App --> Chat[ChatRuntime]
    App --> Ops[OperationRuntime]
    App --> Inputs[PhaseInputs]
    App --> Store[SQLiteStore]
    Chat --> Intake[IntakeProcessor]
    Chat --> Therapy[TherapyProcessor]
    Ops --> Assessment[AssessmentProcessor]
    Ops --> Review[PostSessionProcessor]
    Inputs --> Store
    Intake --> SessionLLM[Session gateway]
    Therapy --> SessionLLM
    Assessment --> SupervisorLLM[Supervisor gateway]
    Review --> SupervisorLLM
    Store --> DB[(SQLite WAL)]
```

The managed launcher runs API and console in one foreground invocation with an ephemeral loopback port. The standalone server is also available. The console still goes over HTTP; it does not import backend implementation types. The framework boundary is real and tested, not merely a diagram. See [local.py](../src/jung/local.py), [server.py](../src/jung/api/server.py), [composition.py](../src/jung/composition.py), and [dependency tests](../tests/unit/architecture/test_dependencies.py).

Composition always creates two SDK adapters, even when both use identical endpoint/model settings. Six source-defined tasks are injected into four processors. `ObservedLLMGateway` optionally wraps each adapter. The application has one mutation lock; chat has a separate generation reservation; retrospective work has one owned asyncio task. Connections are opened per whole synchronous store call, through `asyncio.to_thread`. Cancellation drains in-progress store work before releasing ownership. These mechanisms solve real acceptance/commit races.

## Durable state and workflow

The six tables in [schema.sql](../src/jung/persistence/schema.sql) are `profile`, `sessions`, `messages`, `plans`, `grounded_patient_turns`, and `operations`; schema version is **7** in [_sqlite_support.py](../src/jung/persistence/_sqlite_support.py).

- `messages` are the durable wording owner. A user/assistant pair shares `(session_id, client_message_id)`. SQL enforces role-specific uniqueness and session sequence uniqueness.
- `sessions.intake_record_json` contains the intake record; `sessions.review_json` contains the typed therapy-session interpretation, handoff, recommendation, and generation metadata.
- `plans` are immutable applied revisions. The profile points to the current one; each therapy session points to its starting plan.
- `grounded_patient_turns` stores message IDs only. It has no date, selection rationale, or selecting-review column; those require joins/reconstruction.
- `operations` stores assessment/post-session lifecycle. Assessment product output lives in its `result_json`; post-session result is only completion metadata.

Stage is derived in [workflow.py](../src/jung/workflow.py): `SETUP → INTAKE → ASSESSMENT → STYLE_SELECTION → READY ↔ THERAPY → POST_SESSION → READY`. Failed current operations still block progression. Only retryable failures expose retry; invalid model output is not classified retryable. Profile edits stop after intake; selected style cannot subsequently change.

SQLite enforces one open session and one current pending/running/failed operation. Store transactions enforce additional state and citation invariants. Application and store both check relevant preconditions; these are not entirely interchangeable: the store protects transactions even if called incorrectly.

## Flow A: accepted intake turn to initial plan

1. `POST /api/v1/chat` validates a `ChatRequest`. Request middleware establishes `request_id`; the API opens an NDJSON stream.
2. [ChatRuntime._accept_chat_command_locked](../src/jung/_application/chat.py) first checks existing message pairs. Complete identical pairs are replayed without a model call; conflicting content is rejected; an eligible unanswered user can be retried.
3. Under application mutation ownership, Jung reserves generation and commits the user message. A different unanswered user blocks a new turn.
4. [PhaseInputs.build_intake_turn_input](../src/jung/_application/inputs.py) loads profile, session record, transcript, latest user, previous assistant, and patient-turn count.
5. [IntakeProcessor.prepare_turn](../src/jung/phases/intake/processor.py) calls `intake_patch` for an `IntakeExtraction` candidate list. [extraction.py](../src/jung/phases/intake/extraction.py) maps candidates into nested evidence and injects source sequence/role and `direct_ask`.
6. `direct_ask` is derived from **the intended prompted item**, with the first patient turn treated as presenting problem. The previous assistant text is supplied to the model, but deterministic code does not prove that the generated assistant actually asked that question.
7. [merge.py](../src/jung/phases/intake/merge.py) checks normalized quote containment, drops invalid evidence, and merges scalar evidence by model confidence, then longer value on equal confidence. A later correction does not inherently win. A broad merge exception becomes `merge_failure` with the old record retained.
8. [completion.py](../src/jung/phases/intake/completion.py) distinguishes hard/soft items, informative/addressed answers, direct asks, and 3/12-turn thresholds. Twelve turns is not a universal hard limit: all hard items must be addressed, and extraction failure can block the max-turn path.
9. Only then does `intake_response` stream natural language. No record change is committed yet. If response generation fails, the already accepted user survives but the new intake projection does not.
10. On success, one store transaction writes the assistant and record. The final-intake variant also closes intake and inserts a pending assessment. Scheduling happens after commit.
11. [AssessmentProcessor](../src/jung/phases/assessment/processor.py) makes one supervisor structured call with the intake JSON, last 20 transcript turns, profile name/language, and every style's assessment instructions.
12. Actual output is **one score, rationale, topics, and complete initial plan per style**. Validation requires exact catalog coverage and normalizes order by score/catalog order. `select_style` chooses the corresponding already-generated plan, with no further call.

Documentation discrepancy: architecture/API prose describes style-neutral initial plan material, but [AssessmentResult](../src/jung/phases/assessment/models.py), its prompt, and [TherapyApplication.select_style](../src/jung/application.py) implement per-style plans. Some workflow transition prose also mentions profile revisions after post-session; the actual completion transaction does not update inferred profile facts. The migration must replace these descriptions coherently, not preserve the discrepancies.

## Flow B: live therapy and failure

The same acceptance/streaming path invokes [TherapyProcessor](../src/jung/phases/therapy/processor.py). It performs **one text call**. Input assembly loads the linked plan/style, active transcript, every session (including review documents), and every grounded message, then sorts/extracts prior reviews in Python.

The [therapy context builder](../src/jung/phases/therapy/context.py) packs a 12,000-character historical subtree, with a 2,000-character plan ceiling and at most 12 historical transcript-turn candidates. Current patient text and system instructions are outside that ceiling. Recent complete turns outrank richer briefing/plan content; grounded wording comes last. Grounded historical messages are rendered as content only, without date or source identifier.

The adapter streams ordinary `content`; it ignores `reasoning_content`. The application buffers the final text, rejects blank output, then commits the assistant. Tokens are tentative until `message_completed`. A disconnect can leave an unanswered user; reconnect reads state/history and retries the same ID. Shielded commit work can finish during cancellation, so the client must reconcile durable state rather than assume failure. See [chat tests](../tests/integration/application/test_application_chat.py) and [API resilience tests](../tests/integration/api/test_api_resilience.py).

Starting a therapy session only creates the session; it does not invoke the processor's opening-turn path. The opening capability in phase prompts/tests should not be mistaken for an automatic production opening.

## Flow C: completed session to later context

```mermaid
sequenceDiagram
    participant C as Console
    participant A as Application
    participant D as SQLite
    participant R as Supervisor
    participant T as Conversation model
    C->>A: end_session
    A->>D: Close therapy + create pending operation (one transaction)
    A-->>C: POST_SESSION snapshot
    A->>D: Mark operation running
    A->>R: Analysis JSON request with bounded transcript projection
    R-->>A: Analysis + sequence citations
    A->>A: Validate visible sequences, roles, chronology; resolve full turns
    A->>R: Update request with frozen analysis/evidence projection
    R-->>A: Briefing + plan patch
    A->>A: Validate merged plan; detect no-op
    A->>D: Review + grounded IDs + optional plan + operation complete (atomic)
    C->>A: Start next session, then send message
    A->>D: Read plan, latest prior briefing, grounded statements
    A->>T: Next-session conversation context
```

[PostSessionProcessor.process](../src/jung/phases/post_session/processor.py) has a useful deterministic zero-call path for empty, user-only, or assistant-only transcripts. Conversational sessions require two serial structured calls:

- Analysis: a 12,000-character **user-message** limit. It seeds a fitting user/assistant pair, packs additional whole turns, enriches plan, then tries historical context. The complete stored session may therefore not be analyzed. A visible-sequence allowlist prevents citations to omitted turns.
- Update: an 8,000-character user-message limit. [update_context.py](../src/jung/phases/post_session/update_context.py) constructs evidence atoms, resolves wording, freezes selected analysis, and progressively enriches other fields. The update prompt calls the validated analysis the authoritative account, although citation validation does not establish its semantic truth.

The [evidence validator](../src/jung/phases/post_session/evidence_validation.py) checks existence, role, visibility, uniqueness, and temporal ordering. A later cited patient turn does **not** prove that an intervention worked, or even that it was the semantic response to that intervention. Interpretive lists are not individually required to cite supporting text.

[SQLiteStore.complete_post_session](../src/jung/persistence/sqlite_store.py) resolves selected patient sequences again against source-session messages and commits review, references, optional plan, current-plan pointer, and operation completion together. An update failure loses the in-memory analysis; retry reruns the operation. The latest prior briefing is loaded even when that review created no new plan. Grounded selection is durable without a retention cap, but prompt inclusion is not guaranteed.

## LLM transport, configuration, and reliability

The actual boundary is [OpenAICompatibleLLM](../src/jung/llm/openai_compatible.py), using `AsyncOpenAI` with `max_retries=0`. It supports `json_schema`, `json_object`, and prompt JSON. [structured.py](../src/jung/llm/structured.py) transforms/validates the strict schema, removes a surrounding JSON fence, validates Pydantic output, and constructs a correction request. Structural or processor semantic errors get at most one correction. Transport failures do not. Main's intake prompt is `intake-v3`; it lacks the Phase-10 instructions explicitly classifying clear denials as informative and limiting extraction to addressed safety dimensions.

Important limits of the implementation:

- `finish_reason` is recorded, but neither streaming nor structured code rejects `length`. Nonblank streaming text can be persisted after truncation; a parseable structured value with a length finish reason can be accepted.
- `timeout_seconds` is passed to the SDK request. It is not an explicit total deadline enclosing streaming and correction. A slowly progressing stream and two attempts are distinct time-budget concerns.
- Completion-token caps default to `None`.
- Schema instructions are explicitly appended only for `prompt` mode. `json_object` supplies a JSON-mode flag, not the output schema; phase prose does not enumerate the entire expected schema.
- `ModelPolicy` mixes task policy with model selection and structured mode. There is no configured total context window or runtime capability record.
- Supervisor URL/model/options/credentials independently inherit session fields. Pointing at another origin without clearing secrets can inherit credentials. The eval patient resolver already has more careful cross-origin handling.
- There is no provider discovery, inference-process manager, fallback router, embedding store, or model-switch scheduler. Their absence is appropriate for the current product.

## Diagnostics, evaluation, and tests

Ordinary logging and opt-in diagnostics are parallel systems. [_application/diagnostics.py](../src/jung/_application/diagnostics.py) sends command/transitions only to the optional recorder; it does not emit those events to ordinary logs. [tracing.py](../src/jung/llm/tracing.py) adds logical-call observation; the concrete adapter separately records provider attempts and exposes a metrics callback.

[DiagnosticRecorder](../src/jung/diagnostics.py) owns schema-v5 events, context variables, ordered writing, secret redaction, private permissions, and write-failure latching. [composition.py](../src/jung/composition.py) automatically takes a full SQLite backup after initialized debug runs, even if the failure concerns one call. `_safe_exception_message` is essentially `str(exc)` with a defensive catch; its name does not make arbitrary exceptions safe for ordinary logs. Some operation paths use `logger.exception`, so exception payload handling deserves explicit attention.

The four live surfaces are distinct and useful in intent:

| Surface | Actual implementation |
|---|---|
| Compatibility smoke | Processor-level local calls plus evidence checks under `tests/smoke` |
| Hard invariants | Canary non-disclosure, exact sentinel resistance, citation integrity, selected post-session safety negation; no dedicated Category-C intake denial test on main |
| Behavioral report | Human-review matrix; full workload documents about 57 requests; successful report generation is not clinical approval |
| Simulation | Real HTTP journey, isolated SQLite, synthetic patient, runtime trace, checkpoints, mechanical audit and narrative artifacts |

The [patient actor](../evals/simulation/patient.py) receives scenario and patient-visible dialogue, not plans/reviews/prompts. Preserve that separation. Main's [runner](../evals/simulation/runner.py) is 1,085 lines and exercises intake → assessment → style → therapy → review. Its [audit.py](../evals/simulation/audit.py) is already 1,905 lines, checking API journey, trace, checkpoints, and durable relationships. The separate Phase-10 intake-forensics and Category-C evidence engines are absent. Audit simplification and preservation of primary failures remain relevant, but the deletion inventory must not count absent files.

The deterministic suite has real strengths: rejection/idempotency, cancellation while persistence is in flight, operation retry handoff, schema invariants, API stream identity/order, prompt budgets, provenance, and eval-harness failure paths. `make check` runs format, lint, local doc links, unit/integration tests, and one console probe. Live tests are excluded.

Historical outcomes are informative but limited. [Phase 8B](../evals/phase8b/OUTCOME.md) did not measure interactive first-token latency; its selected concurrent report configuration had a modest fixture-specific advantage. [Phase 8C](../evals/phase8c/OUTCOME.md) was inconclusive after genuine failures. [Phase 8D](../evals/phase8d/OUTCOME.md) found cheaper synthetic-patient calls with thinking disabled but an older intake path still failed. None admits the proposed architecture; Phase-10 outcomes must likewise retain their exact revision and measured-property limits.

## Safety behavior actually present

Safety screening is intake evidence/completion logic. Patient-facing prompts mention urgent safety/medical content; review/assessment schemas include boundary notes. There is no independently enforced runtime crisis classifier, external emergency action, human monitoring loop, or validated diagnosis engine. Packaged style text is not a substitute for a common safety policy. Existing [safety documentation](../docs/safety-and-data.md) correctly distinguishes narrow hard invariants from diagnostic clinical-style scenarios and unclaimed guarantees.

The architecture should preserve that honesty while improving data integrity and operational boundaries. It should not portray a populated intake safety slot as proof of safety, or an evaluation pass as clinical validation.
