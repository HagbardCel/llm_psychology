# Target runtime and workflows

## System structure

```mermaid
flowchart TB
    UI["Console: patient input, source inspection, retry"] -->|"HTTP /api/v1 + request-owned NDJSON"| API["API: validation, correlation, DTO mapping"]
    API --> App["Application: commands, work ownership, derived stage"]
    App --> Store["SQLiteStore: consistent reads and atomic writes"]
    Store --> DB[("One SQLite database")]
    App --> Conversation["Conversation: intake or therapy prompt"]
    App --> Review["Review: retrospective result + semantic validation"]
    Conversation --> Context["Context functions: select, label, budget"]
    Review --> Context
    Conversation --> Gateway["Model boundary: text / structured"]
    Review --> Gateway
    Gateway --> A["Conversation endpoint"]
    Gateway --> B["Review endpoint; defaults to A"]
    API -.-> Logs["Structured local logs"]
    App -.-> Logs
    Gateway -.-> Logs
    Eval["Test/eval process: isolated data"] -.->|"same API; own evidence"| API
```

No actor gets tools to mutate the database, run commands, browse patient files, or invoke another actor. Models return text or a proposal. Jung validates and commits.

Suggested final layout, with names illustrative and ownership normative:

```text
src/jung/
  api/                 # existing adapter/contracts/server
  client/              # existing HTTP client and console
  domain/              # Profile, Session, Message, Plan, Review; typed errors
  persistence/         # SQLiteStore, schema, row decoding
  conversation.py      # intake/therapy prompt modes; natural text only
  review.py            # one retrospective prompt and result validation
  context.py           # query inputs, labeled sections, whole-item packing
  llm/                 # protocol, endpoint profiles, SDK adapter, correction
  application.py       # use cases and derived snapshots
  _application/
    chat.py            # acceptance/stream/commit ownership
    review_work.py     # one owned review task and recovery
    store_calls.py     # cancellation-safe whole store calls
  workflow.py          # short pure policy over durable facts
  logging.py           # setup, context fields, safe metadata/payload handlers
  composition.py       # acquire data-dir process lock, construct and close resources
  config.py            # sole configuration loader
  local.py             # foreground launcher
  styles/              # descriptions and concise method instructions
```

Do not reorganize unaffected API/client files simply to match this picture. A separate processor class is unnecessary if a prompt function plus a narrow call suffices. Keep a small model protocol for fakes; no factory registry, base-agent class, or dynamic task dispatch.

## Workflow state and concurrency

Four displayed stages are enough: **INTAKE, REVIEW, READY, THERAPY**. Review has pending/running/failed status, shown alongside the stage. It is not a second mutable stage field. Method and language settings do not require a SETUP stage.

Derivation order:

1. A closed session with unfinished review → `REVIEW`.
2. An open intake or therapy session → corresponding active stage.
3. An applied current plan and no unfinished work → `READY`.
4. Any other combination → an invariant error, not a default stage.

Fresh-database initialization atomically creates the singleton profile and one intake session with English and a small supportive-style entry as defaults. Display those editable defaults without implying that the patient explicitly chose them. Initialization is idempotent and never manufactures a new intake to hide an inconsistent existing database. Display name, date of birth, and free-form profile notes are removed from this minimal target because they have no demonstrated target consumer; no console name-personalization feature is required. Patient narrative belongs in messages. These omissions are a product scope choice, not a prohibition on later age-appropriate requirements.

Keep the mutation lock around command acceptance/commit, and a generation reservation across a chat attempt. One review task runs while the stage is `REVIEW`; another session cannot begin against an unfinished review. Reads remain available. Never hold a SQLite transaction across a model await.

The backend also takes an OS advisory lock for the configured data directory at startup and holds it through shutdown. A second backend using that directory fails clearly. This small local lock prevents a second process from treating the first process's active review as crashed; SQLite's writer lock alone does not establish process ownership. Disposable evals use different directories. No lock service is required.

| Stage | Commands |
|---|---|
| INTAKE | Chat; finish intake after at least one nonblank patient message; edit method/language while idle |
| REVIEW | Read state/history; retry a failed or unscheduled review when idle; stop the application |
| READY | Start therapy; edit language; method remains fixed |
| THERAPY | Chat; end session; edit language only between turns, effective for future sessions; method remains fixed |

The profile is the sole durable owner of `method`; each session stores only a scalar `language`, not `preferences_json` or a method copy. During intake, idle method edits update the profile; language edits atomically update `profile.current_language` and the open intake's `language`. They affect subsequent replies without rewriting past messages. Finish Intake closes intake and queues review in one transaction, making the profile method immutable and freezing intake language. An edit racing with closure is serialized by normal command ownership. Reject method changes after closure, including while initial review is pending or failed; do not silently accept or queue them. The closed intake establishes this invariant without another lock flag or SETUP stage.

All therapy conversations and reviews obtain the same immutable `profile.method` and their session's `language`, alongside the applicable plan and latest useful handoff. No method-mismatch projection, pending method change, transition-specific replacement rule, or pre-session planning call is needed. Method is not a plan property, stored or derived through its source session. Switching method is a deferred product feature that would need its own revision/provenance semantics and transition design for both plan and handoff.

Language remains editable while idle. At therapy session creation, copy `profile.current_language` into `sessions.language` and freeze that scalar; later profile language edits are visibly pending for future sessions. Review retries use the session language and immutable profile method, so a generic preference snapshot is unnecessary. Merely editing language or opening an empty session does not generate a plan; deterministic no-conversation review remains no-change.

## Intake

1. Console displays the initialized language/style defaults and a short orientation: concerns, impact/time course, goals, coping, and safety can be discussed; unknowns and declining to answer are acceptable.
2. Intake already exists with editable method/language and no initial plan. A static welcome invites the first patient contribution; it is UI guidance, not fabricated therapist dialogue. No explicit method/language confirmation is required to begin.
3. Patient text uses the ordinary durable chat path. The conversation task in intake mode asks concise follow-ups based on the recent transcript. There is no extraction call and no durable inferred intake record.
4. Keep an always-available explicit help action. Safety disclosures and denials use ordinary free text and remain complete message sources. Typed self-report controls are deferred until an independent product requirement justifies them; no extraction replacement or structured safety fields are part of R2.
5. **Finish intake** is an explicit user command. It does not certify clinical completeness or safety. Accept it after one patient message, even if questions remain. It freezes the profile method and intake session language, closes the session, and queues review in one transaction. A trailing unanswered message remains source material for that review.
6. The initial review reads the full intake and produces a provisional plan and handoff. It records unknowns and questions for later clarification. A valid initial review requires a plan; it does not require a diagnosis or style score.
7. Commit and enter `READY`. No assessment operation, catalog coverage validator, or post-assessment style-selection stage remains.

R2 keeps chat input to session, client message identity, and text. Exact denial retention, actual review selection, and inclusion in the next context have distinct checks; storing raw text alone does not establish semantic continuity. R6 measures this baseline; only an evidence-backed optional R6a adds explicit recall metadata together with browsing, selection, persistence, and idempotency support.

## Live therapy

```mermaid
sequenceDiagram
    participant U as Console
    participant A as Application
    participant D as SQLite
    participant L as Conversation model
    U->>A: Chat(session, client message ID, text)
    A->>D: Resolve duplicate; check live context and fixed session-source limit
    A->>D: Commit patient message
    A->>A: Select and budget context from consistent source reads
    A->>L: Instructions + labeled context + recent exchanges + current input
    L-->>U: Tentative tokens through A
    L-->>A: Valid stop and nonblank final content
    A->>D: Commit assistant + small generation metadata
    A-->>U: message_completed
```

Same-ID retries reuse or regenerate the same accepted user message; changed content is a conflict. Optional R6a extends that equality to explicit recall metadata only if introduced. A partial stream is not a completed therapeutic record. If the provider ends with truncation, missing terminal status, refusal/filter failure, or blank text, no assistant completion is committed. The console marks any displayed partial as interrupted and offers retry/end; it must not leave it looking like a successful answer.

Retain the existing four NDJSON event shapes unless a specific UI need requires a change. Cancellation closes the SDK stream and drains critical database work before releasing mutation ownership. If cancellation occurs after commit but before the terminal event arrives, the client reconciles through history. There is no exactly-once-delivery claim over HTTP; there is idempotent durable acceptance/completion.

## Completion and retrospective work

Ending a therapy session atomically sets `ended_at` and review status `pending`. The response is immediately accepted; review outlives the HTTP request. Starting another session waits for successful review, preserving coherent plan/handoff ownership.

Review input contains the full completed session, starting plan, immutable profile method, frozen session language, latest useful prior handoff, and a small dated patient-source selection. The plan/handoff are labeled generated guidance; earlier review notes are excluded initially to limit repeated interpretation. The same processor handles initial intake and later therapy, with explicit initial-plan requirements.

Output sections are:

- **Session note:** short account, supported observations/hypotheses or uncertainty, and safety/boundary observations. No separate unresolved-question list.
- **Handoff:** opening direction, limited carry-forward questions/directions (including session-specific restrictions), and a few source handles. Enduring restrictions belong in plan cautions; no separate avoid list.
- **Memory selections:** up to five patient source handles, without purpose labels or purpose-based priority.
- **Replacement plan or null:** full bounded strategy when change is warranted. No sparse patch language.

Validate fields, references, visible-source membership, source roles/session membership, and plan requirements separately. Current/historical labels come from resolved sources, not a model-authored scope field. Then one transaction writes review, references, optional plan/current pointer, and completion. The plan row owns its source-review link; review JSON stores no reverse resulting-plan ID. Application code resolves handles and authors provenance. The compact schema and one-call decision must pass R0b on R1's boundary before cutover.

Empty therapy sessions take a deterministic no-change path. Therapy with only an unanswered patient contribution also takes a deterministic review indicating that it was not explored; its source is retained and presented at the next session. Do not infer disengagement. Intake with patient text still needs the initial review even if no assistant completed, because it must establish a provisional plan. Empty intake cannot finish.

For no-content therapy reviews, `handoff` is null and the next context uses the latest earlier non-null handoff. An unanswered patient source from the immediately preceding session is independently included through a direct store query; it must not disappear merely because the no-content review had no new handoff. See context construction in the [data and context model](04-data-and-context-model.md).

## Review recovery

```mermaid
stateDiagram-v2
    [*] --> Pending: Session closes
    Pending --> Running: Owned task claims session and increments attempt
    Running --> Complete: Validated artifacts commit atomically
    Running --> Failed: Model/validation/application failure
    Running --> Failed: Startup finds interrupted work
    Failed --> Pending: Explicit retry after diagnosis/config correction
    Pending --> Running: Startup resumes accepted unscheduled work
    Complete --> [*]
```

Use conditional SQL updates on `(session_id, review_status, review_attempt)` to fence a late worker. The attempt is monotonic per session; it is not a workflow revision token sent by the client. Completed review content is immutable in the supported command surface. Retrying a failed review does not create another session or duplicate plan/reference rows.

Keep this lifecycle to status, attempt, bounded error metadata, and the single owned asyncio task. Do not add worker identities, leases, attempt-provenance tables, or recovery machinery for hypothetical parallel workers.

On startup, pending accepted work is scheduled. Stale running work becomes failed/interrupted and requires an explicit retry; do not repeatedly call a failing model on every application restart. This deliberately changes today's automatic running → pending recovery. A lost worker-scheduling attempt leaves visible, resumable pending work; retry/resume can schedule it without pretending it ran. Shutdown waits up to its configured grace period, then cancels/drains the owned task. It does not manufacture successful review.

Allow explicit retry for invalid output and endpoint/configuration failures after the operator changes the relevant settings, as well as transient outages. A retry is a new deliberate logical call with at most one correction. Eligibility is derived from a closed failed/pending session and currently valid workflow preconditions, not a permanently stored `retryable=false` bit. Corruption/invariant failures require repair and fail those preconditions until repaired; there is no “skip review and silently advance” command.

## Model topology and configuration

Two small types, `CallPolicy` and `EndpointProfile`, represent two task policies and at most two resolved endpoints. Capability fields belong to the endpoint profile; the rows below describe ownership, not a registry or extra configuration hierarchy:

| Concern | Owns | Does not own |
|---|---|---|
| Task policy | `conversation` or `review`; temperature; output reserve; total deadline; prompt version | Endpoint URL/model identity |
| Model capability | Configured context window; admitted structured mode; finish/stream behavior; token-limit parameter support | Clinical authority, workflow routing |
| Runtime profile | URL, served model ID, explicit secrets/headers, provider-specific extras, reasoning options | Completion criteria, persistence, retry policy |
| Application | Call ordering, source access, context selection, semantic validation, acceptance/commit | Inference scheduling, KV-cache implementation, weight loading |

Default review profile is the **same profile object** as conversation. One HTTP client can be shared for an identical endpoint credential set. If a separate review profile is specified, its URL/model and credentials are explicit; missing credentials do not inherit across origins. A single server serving multiple admitted model IDs can share transport while choosing the configured model. Avoid “inherit each nullable field independently” semantics.

Retain one `load_settings()` owner using existing `pydantic-settings` and `.env`. Environment values override dotenv values, which override defaults. Do not introduce TOML, secret-name indirection, or another configuration parser. Once six tasks have become two, R5 removes obsolete task overrides and reduces settings to the endpoint/call-policy fields that still have consumers. Cross-origin credential isolation is an earlier R1 correctness fix, not dependent on this redesign. Unknown endpoint/policy keys fail validation.

Initial engineering defaults to test in R0b are 768 completion tokens / 120 seconds for conversation and 3,072 completion tokens / 300 seconds for review; they are not promises about all local models. Bound every output and reserve reasoning within the provider's total completion budget. Also enforce a finite response-byte limit (initially 8 KiB for conversation), so acceptance can reserve a maximum assistant source size using the same canonical source serializer as review. Exceeding it interrupts the attempt without a completed assistant row. If a server distinguishes visible-output and total-output limits, its endpoint profile must name the supported behavior. R0b freezes suitable limits on the corrected R1 boundary, including the session-source maximum and bounded non-session allowance.

### Runtime-specific guidance

Use OpenAI-compatible Chat Completions as the only production wire protocol. llama.cpp documents streaming chat, schema-constrained output, template/tokenization endpoints, and slot-related controls; those capabilities belong to the server. Its own documentation cautions against assuming perfect OpenAI equivalence. Verify the actual build and request shape. [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)

MTPLX also exposes an OpenAI-compatible server and manages model/runtime acceleration. Its upstream changelog describes schema constraints using llguidance, but that does not establish that an arbitrary installed build or launch configuration enforces Jung's schema. The repository's older missing-llguidance failure illustrates why admission should be version/configuration-specific. Jung should neither install llguidance nor manage MTP/KV caches inside its runtime. [MTPLX server documentation](https://github.com/youssofal/MTPLX/blob/main/README.md), [MTPLX changelog](https://github.com/youssofal/MTPLX/blob/main/CHANGELOG.md)

`/v1/models` can check a configured served ID. It is not a universal capability negotiation protocol: context and constrained-generation behavior require documented settings plus real admission requests. A manual `check-model` command may print observed/configured capabilities and run synthetic probes. Admission must exercise the actual review schema and full product envelope, including multilingual source and bounded correction/output. Normal startup validates the configured endpoint's capacity against that fixed envelope without therapeutic or expensive test calls. Re-admit a changed server/model configuration; do not add a profile registry or persisted per-session capacity fingerprint.

One resident model is the operational baseline. If two models do not fit comfortably, configure runtime-managed loading at session boundaries or manually run review later on the appropriate server, then retry the pending session. Jung does not become an inference supervisor. No silent fallback to a cloud endpoint or another model is allowed. Hot model switching mid-stream is unsupported; finish/cancel work and reload validated configuration.

## Structured output and error behavior

Natural text is right for conversation: no JSON wrapper, action parser, or model-authored stage transition. Review needs structure because references and plan changes become durable data.

Target `json_schema` as the sole production review mode. R0a designates one required local runtime before final tests; R0b admits its actual model/server/configuration with the compact schema on R1's corrected boundary. Additional llama.cpp, MTPLX, or other configurations need separate admission before support is advertised, but do not block canonical cutover. Their incompatibility does not automatically add another mode. Any exception requires a named required endpoint and measured need; no automatic downgrade. R5 separately admits public SDK parsing and revalidates affected properties. Structure is not truth. Parse a complete JSON object; do not infer missing fields or use partial recovery. [Pydantic JSON documentation](https://pydantic.dev/docs/validation/latest/concepts/json/)

One logical review call:

```text
prepare fixed input and output budget
within one total deadline:
    send attempt 1 with SDK retries = 0
    require valid terminal status and content
    parse schema and validate section semantics
    on correctable schema/semantic failure only:
        send attempt 2 with original input + bounded error locations
        apply exactly the same validation
return complete valid result, or fail without writes
```

Correction is at most one, not guaranteed: no call begins after the deadline or if the correction prompt cannot fit. A broken reference is correctable; a database read bug is not. Timeout, cancellation, transport failure, refusal/filter response, and length truncation do not trigger “try another provider” or an automatic continuation. Blank review content may use the one correction if transport completed normally; blank conversation fails immediately.

| Failure | Durable result / visible behavior |
|---|---|
| Invalid chat input, duplicate conflict, known request too large | Reject before acceptance; preserve client draft |
| Model unavailable / 429 / 5xx | Accepted user survives; review becomes failed; explicit retry |
| SDK timeout / outer deadline | Same; cancel request and close stream |
| Nonblank text with `finish_reason=length` | Interrupted attempt; no assistant commit |
| Stream EOF without required terminal finish | Protocol failure; no assistant commit |
| Structured JSON parse/schema/reference failure | One correction; then failed review with no partial artifacts |
| Parseable structured result with length finish | Truncation failure; no commit, no implicit acceptance |
| Refusal/content filter | Typed failure; no reinterpretation as a clinical finding |
| Provider uses only `reasoning_content` | No usable content; change runtime reasoning configuration, never display hidden reasoning as therapist speech |
| Unknown provider option / unsupported schema mode | Configuration/protocol error; no mode fallback |
| User disconnect | Cancel generation; accepted/committed state reconciled from DB |
| SQLite error during completion | Entire artifact transaction rolls back; no successful terminal event |
| Crash during review | On restart show interrupted review; explicit retry |
| Log/capture failure | Warn once; product outcome unchanged; any dependent hard evidence claim fails |

Use stable public error codes: retain `invalid_command`, `busy`, `not_found`, `llm_unavailable`, `llm_timeout`, `invalid_llm_output`, and `internal_error`; add explicit `context_capacity`, `llm_protocol_error`, `llm_refused`, and `interrupted` where applicable. Truncation is `invalid_llm_output` with a safe reason code. Keep transport status separate: command conflicts are HTTP 409, unknown resources 404, invalid bodies 422, known capacity rejection 413, and unavailable application 503. Once an NDJSON stream is open, its terminal failure envelope carries the corresponding code instead. Never embed raw provider text in that envelope.

Default streaming admission requires the terminal status Jung relies on. A runtime omitting it is incompatible until a narrowly specified adapter change is justified and tested. Do not declare every OpenAI-compatible server supported merely because it accepts a request.
