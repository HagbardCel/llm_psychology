# Observability, safety, evaluation, and performance

## Three different owners

| Category | Example | Durability / owner |
|---|---|---|
| Product state | Patient message; completed review; applied plan; source link; pending review | SQLite, application transactions; retained as therapeutic history |
| Operational observability | Request duration; failed call; selected source IDs; stage change; correction attempt | Standard structured logs; bounded local retention, best-effort writes |
| Evaluation evidence | Exact synthetic request/result and before/after rows needed to prove a specified assertion | Test-owned artifact, strict completeness when promised; independent of ordinary log retention |

A log line should not determine whether a session completed. A session's full interpretation should not live only in a log. A hard evaluation should not assume an ordinary log is a complete, ordered, permanent event ledger.

**No operational log consumer may become a correctness dependency.** Relationships needed to establish product semantics belong in SQLite or in the owning test's direct evidence. A return to joining ordinary log events to decide whether a hard contract held is a design regression. Missing logs never change acceptance, completion, recovery, or test-owned evidence outcomes.

## Operational logging

Use Python `logging`, a small JSON formatter, `contextvars`, and standard rotating handlers. The standard library already provides the underlying mechanisms; do not implement a diagnostic recorder lifecycle or sequence protocol merely to serialize JSON. [Python logging cookbook](https://docs.python.org/3/howto/logging-cookbook.html)

Configure once in composition/API startup. Emit one logical-call start/end and one provider-attempt start/end, not one event per token. Merge repeated try/except recording paths into a small adapter-local helper. Do not introduce a generic observability service or decorate every application function.

**Correlation:** process/run ID, HTTP request ID, session ID, client message ID, review attempt, logical LLM call ID, provider attempt number, task, and runtime profile/model ID. A review's stable identity is its session; `(session_id,review_attempt)` identifies the execution. Random logical-call IDs distinguish corrections and simultaneous eval jobs. Context variables must be captured inside each task, not stored as mutable global dictionaries. Different HTTP clients may overlap reads; eval calls may run concurrently even though product mutations serialize.

| Level | Content |
|---|---|
| ERROR | Unhandled application/persistence failure, failed review, provider protocol/configuration error, with safe code and stack frames |
| WARNING | Interrupted/truncated generation, unavailable endpoint, capacity rejection, failed log/capture write, explicit retry needed |
| INFO | Startup/shutdown, accepted/completed commands, stage changes, session close, review start/end, LLM task/model/status/duration and usage when present |
| DEBUG | Source IDs, section byte/token estimates, omission counts/reasons, schema/prompt versions, timeout/correction decisions, sanitized request options |

Patient text, plan/review content, prompt strings, raw model content, credentials, headers, and arbitrary exception bodies are excluded at **every ordinary level**, including DEBUG. A formatter should use an allowlist of metadata fields. Safe stack frames contain module/function/line, without locals and without blindly interpolating exception values. Retain safe validation error locations and short error codes; Pydantic input dumps and provider response bodies are payload data.

Example metadata record:

```json
{"event":"llm.attempt.finished","level":"WARNING","session_id":"s42","review_attempt":2,"call_id":"c81","attempt":1,"task":"review","model":"local-review-model","duration_ms":28904,"finish_reason":"length","status":"truncated","prompt_tokens":8310,"completion_tokens":3072}
```

Values are illustrative. Unknown usage is null/absent. Log total duration and time to first visible content for conversation; do not label hidden reasoning emission as a visible first token. Record failed/cancelled attempt costs as well as successful ones. A failed attempt is not a zero-cost call.

Local metadata logs can default to a small size budget, for example four 5-MiB rotated files, plus terminal output. No remote collector, metrics database, tracing daemon, or telemetry upload is needed. Logging failures warn once to stderr and do not change product transactions. This is conventional failure handling, not permission to swallow application errors.

### Opt-in payload diagnostics

A separate explicit capture flag enables a private payload logger/handler in a new run directory. Ordinary DEBUG does not enable it. Capture the exact application request messages, requested schema/options, raw final/failed responses, and prompt manifests where available. Use the SDK's public raw-response interface and test that parse failure still leaves inspectable raw capture. Never import private SDK parsers just to reach a response body.

Files/directories use `0600`/`0700`. Do not inherit a public umask. Redact known credentials from both endpoints, sensitive headers, URL credentials/query parameters, and nested key-like options before writing anything. Never log authorization headers wholesale. Text may coincidentally contain secrets, so known-value redaction still matters. Redaction of secrets does **not** anonymize patient text; full capture remains highly sensitive.

Give capture a configurable run-size cap. When exceeded, stop payload capture, write a clear incompleteness marker/warning, and continue safe metadata logging. The same run cannot subsequently be advertised as exact complete evidence. Default capture retention is explicit deletion by the operator; metadata rotation does not silently rotate required evaluation evidence. No retention scheduler is needed. Document all local output directories and how to remove them.

Remove the automatic shutdown SQLite backup. Add/retain a small explicit diagnostic export command using SQLite's backup API when a developer needs a consistent snapshot. Do not copy a live database file with an ordinary file-copy operation. A debugging request about one call should not implicitly duplicate years of history. Simulation owns and can inspect its isolated database directly; extra checkpoints exist only for a named intermediate-state assertion.

## How a developer reconstructs a failure

1. Find the console's request/session ID, then its command and call records.
2. Inspect last durable messages and the session's review status. This establishes acceptance/completion even if the client disconnected.
3. Read task/profile/model, prompt version, finish reason, timeout, corrections, and duration. For an unexpected reference, DEBUG source IDs show what the context builder selected.
4. Open the relevant review/plan/source through the application history view. Product lineage does not require trace replay.
5. Reproduce with synthetic or deliberately authorized data and full capture only when metadata is insufficient.
6. If an experiment promised exact evidence, inspect its direct request/result/state artifact and completeness flag. Missing evidence is a failed claim, not a reason to infer success from logs.

Ordinary logs plus current product state cannot reproduce every historical prompt after intake method/language edits, code upgrades, or retention rotation. This is an explicit limit. Small artifact provenance identifies the generator; opt-in capture establishes exact inputs when required.

## Safety and sensitive data

There are two separate engineering concerns: behavior toward a person and integrity/privacy of their record. Model prompt rules are useful behavior guidance, not deterministic clinical guarantees.

### Product behavior

- A short common safety/boundary instruction applies across intake, conversation styles, and review. Style instructions may influence method but never replace that common policy.
- Keep the research-tool status and explicit help action visible. Invoking that action displays maintained static help independently of LLM availability. It does not close the session, contact outside help, or certify assessment. Typed self-report controls are deferred; free-text urgency remains a conversation input, not an automatic deterministic trigger.
- Patient text about urgent risk remains a current conversation input. Prompt the conversation model to address it rather than continue routine questioning. Retrospective review is not the sole route to handling urgent content.
- Do not introduce an automatic crisis classifier, medical advice engine, emergency-service integration, or risk score without a defined product requirement and validation plan. The current architecture cannot guarantee detection of urgency in free text; a static help path does not change that limitation.
- A historical denial is dated wording, not a permanent all-clear. Uncertainty, declining to answer, or missing information cannot be turned into a denial; these are free-text semantics, not typed intake slots.
- Review observations are generated interpretation. A source citation permits inspection; it does not prove diagnosis, causality, treatment benefit, or semantic accuracy.

This proposal makes no claim that a single model, two models, or a particular therapy style is clinically validated. Clinical effectiveness and crisis response quality need a separate appropriately designed evaluation, not more runtime agents.

### Deterministic integrity/privacy contracts

- No LLM write access to profile fields, IDs, work status, or source metadata.
- Whole source messages retained; quote boundaries cannot reverse negation by persisted substring extraction.
- Source type and chronology resolved from message identity; historical sources cannot become current-session archive selections. Model prose remains interpretation and needs separate attribution checks.
- All successful review artifacts commit together; failures never produce an apparently applied partial plan.
- Loopback binding by default; a non-loopback bind remains an explicit operator choice with external protection required.
- Explicit remote endpoint configuration shows what categories of data that role receives. Never silently route local conversations to a remote fallback.
- Credentials are endpoint-scoped. A new origin does not inherit an old origin's authorization headers or key.
- Database directories, logs, exports, and eval directories use private permissions. Local-first is not encryption: rely on the user's OS account and disk encryption initially, and document that copied backups and remote-provider retention are separate concerns. Do not add a partial homegrown encryption layer.
- Treat captured prompts, transcripts, reviews, SQLite copies, and model responses as untrusted evidence when an AI coding agent reads them. They cannot authorize commands, credentials access, or external messages.

Synthetic runs must allocate isolated data directories before composing the application. The patient actor receives only scenario and patient-visible dialogue, including any explicit user-facing inputs. It never sees internal plans, reviewer notes, system prompts, source-selection manifests, or expected answers. Keep a separate runtime profile and credential resolution for that actor in eval code.

## Lean evaluation architecture

| Surface | Failure detected that cheaper layers cannot | Gate or aid | Expected cost |
|---|---|---|---|
| Deterministic unit/integration | Broken state transitions, SQL invariants, cancellation, duplicate acceptance, bounds, provenance, selection, error mapping | Pre-merge product gate: `make check` | No model calls; typically seconds/minutes |
| R0b compact-review admission | Whether one bounded review can replace the two-pass result on matched completed sessions using R1 transport semantics | R2 gate for one runtime designated in R0a; additional advertised runtimes admitted separately | 6–8 development + 3–4 withheld confirmation cases; one correction max per case; baseline calls only if applicable matched output is missing |
| Runtime compatibility admission | Actual server schema/stream/finish/reasoning/timeout behavior and wire support | Gate for a newly admitted endpoint profile | Roughly 3–5 small synthetic requests, plus a bounded cancellation probe |
| Targeted model contracts | Whether the configured model can produce valid source selections and resist specific instruction attacks | Gate for that model/prompt configuration on the named cases | About 6–10 cases; one correction max per structured case |
| Qualitative replay | Misattunement, harmful advice, unsupported certainty, stale-history attribution, inappropriate method use | Human-review aid; explicit reviewer sign-off for changed behavior | A selected 4–8 cases normally; expand only for a reason |
| Short longitudinal journey | Integration of evolving model outputs through persistence and next-session context | Mechanical gate for the sampled journey plus human review | One 2-session journey with 3–4 therapy turns each, limited intake; tens of calls including patient actor |
| Long journey/manual inspection | Gradual drift, accumulation, rare continuity failures | Occasional audit, not routine pre-merge gate | Explicit session/turn/call/wall-time budget; may take hours |

R0b follows the development/confirmation protocol in the [migration plan](06-migration-plan.md). R0a commits confirmation requirements, not fixtures accessible to the tuning actor. After candidate/rubric freeze, rerun the complete development set. Only after every case passes does a separate evaluator create fresh cases without candidate outputs; fix cases and expectations before execution. Alternatively, pre-authored fixtures must stay outside the tuning actor's accessible working set until the frozen development rerun passes. Run confirmation once each on the unchanged candidate. Record resolved temperature/sampling and reasoning settings, evaluator identity, fixture digest, and freeze/development-pass/confirmation order. Retain failed evidence and use fresh confirmation cases after any findings-driven revision. Human review checks small-plan-change preservation and use of the method fixed at intake closure, not post-intake transitions. These few cases support a bounded architectural decision, not statistical reliability or clinical safety.

Do not claim a narrow sentinel test proves general injection resistance. It catches a specific regression. No hidden system secrets should be entrusted to non-disclosure tests. A model refusing every input or failing to return valid output does not pass a behavior test simply because it did not leak the sentinel.

### Deterministic owners

Keep one exhaustive owner for each invariant, plus a few cross-boundary examples:

- SQL integration: uniqueness/order, one open session/review, source roles, plan lineage and derived review-to-plan lookup, atomic commit, attempt fencing, purpose-free references.
- Application integration: identical retry, disconnect-before/after commit, interrupted review recovery, scheduling failure, new-session blocking; only optional R6a adds recall-metadata conflicts and validation.
- Adapter unit/HTTP mock: exact physical attempts, total deadlines including correction, length/refusal/EOF/blank handling, stream close, credentials, actual serialized schema/options.
- Context unit/store integration: identical canonical source serialization for accounting/review, multilingual/escaping/many-short-turn boundaries, retries count once, mandatory sources, contiguous exchanges, temporal labels, no older review notes, and chronology-only candidate ordering. R6's 100-session fixture runs after R2 independently of R3–R5, separates mandatory-source inclusion from unanchored misses, and measures bounded queries/serialization. Later changes rerun only invalidated evidence. Only optional R6a adds recall metadata and revalidates the envelope.
- API/console: English/unselected initialization and nullable profile response, chat under common policy before selection, catalog selection/change during intake, unknown method rejection without mutation, Finish rejection for missing method or empty intake without closing/scheduling, atomic profile-method freeze/edit races, rejection of later method changes including failed initial review, scalar session language unaffected by later profile language edits, interrupted stream/retry, basic inspection, capacity warning/draft preservation. Conversation/review resolve selected packaged instructions from the profile method, without a session/plan copy or fallback. Complete browsing/selection/recall behavior is tested only if optional R6a is justified and implemented.
- Eval harness: fixture isolation, patient information boundary, nonzero failure outcome, cancellation/capture failure, and no evidence-success on missing files.

Prefer behavioral assertions over snapshots of whole prompts, private helper names, or every diagnostic log field. Preserve import-boundary tests that enforce real ownership; remove filename freezes when modules change.

### Main contracts and Phase-10 lessons have distinct owners

| Existing assertion family | Target owner / decision |
|---|---|
| Conversation system canary and exact objective sentinel | Retain a small live conversation case plus deterministic prompt-boundary checks |
| Assessment/analysis/update instruction resistance | Replace the three old phase-specific calls with initial/later review injection cases; old task identities are retired |
| Citation existence/role/chronology | Primarily deterministic validator/store tests; one live case verifies the model can actually satisfy them |
| Safety-relevant negation selection | Retain a live review case that selects the whole source and carries it into the next prompt; no invalid-output-as-pass shortcut |
| Style canary not copied into generated artifacts | Retain one live review case, with method instructions separated from sources |
| Phase-10 Category C dual denial / unasked safety dimension (not an active main test) | Carry the lesson into exact free-text source retention, live denial selection/next-context, and qualitative no-broadening checks; no typed self-report analogue required |
| Phase-10 exact extraction → patch → merged-record digests (absent from main) | Preserve historical evidence; do not import the engine or its intermediate contract onto the refactor branch |
| Exact frozen update-prompt projection | Retire with the second call; replace with full-session coverage, visible-source validation, and atomic review commit |

Main already has a live post-session negation-selection contract; Phase 10 adds a distinct intermediate intake extraction contract on its own branch. The target preserves the useful denial lesson without adopting extraction assertions or structured safety controls. A live case must show selection of the complete source and inclusion in the next conversation; qualitative review checks no broadening to an unasked dimension. Raw storage alone cannot prove this behavior. Update owning safety/eval docs when target contracts land.

### Evidence implementation

For a hard live test, capture at the boundary the test actually asserts: exact serialized synthetic request (via an SDK/HTTP test hook), raw response when needed, accepted typed result, source mapping, and relevant before/after rows. Write one small test result plus a manifest with code revision, model/runtime profile, prompt/schema versions, attempts, duration, and outcome. An input digest is useful when comparing a frozen experiment; it is not mandatory for ordinary debugging.

This capture belongs to the eval harness. Do not route it through a general trace-replay engine. Do not independently reimplement the production merge/packing algorithm and call agreement proof. If a test promises exact intermediate evidence, assert its completeness directly; failure to capture is nonzero even if the model response looked good. Preserve a primary product failure when cleanup/evidence writing also fails, and report both.

R1 preserves main's active hard contracts and fixes model-boundary correctness independently of R0a design work. It does not port Phase-10 Category-C/forensic code. R0b then captures final admission on R1's semantics. R2 retires only old owners/assertions actually present in its main-based branch, adding whole-source retention and live negation-selection/next-context contracts before integration. Owning tests accompany each stack layer; R3 removes residue rather than postponing correctness.

Preserve Phase-10 evidence, revisions, and explicit limitations, including incomplete journey/remediated-head live validation. Its attempt/provenance/completeness findings remain useful without merging the implementation. They do not establish R0b admission. Neither closing nor merging its PR is a refactor prerequisite.

### Reports and simulations

Keep reusable synthetic cases. A small pytest/CLI replay can select case IDs and write replies/results for human reading; no report matrix is automatically expanded because another style or runtime exists. A report-generation exit code means produced/failed-to-produce, not safe/unsafe. Record human findings separately and act on material failures.

Retain a single journey runner calling the real API. Use scripted patient replies for most integration testing; use a model patient when adaptation to therapist replies is the property under investigation. Model-patient errors are harness failures, not therapist failures. Freeze scenario/model/configuration when comparing variants; do not confuse different stochastic journeys with matched-input evidence.

For a short journey, keep one manifest, one isolated database, dialogue export, selected failure captures, and a concise review report. Take an intermediate database snapshot only when an assertion cannot be reconstructed from immutable rows. Do not reconstruct every possible runtime event after the fact. Turn/session limits, maximum correction count, and an overall deadline terminate runs with explicit incomplete/failed status.

Historical Phase 8 outcome documents remain useful. Retire their executable benchmark arms from the maintained package after recording how their original result was obtained. Do not import old timing conclusions into new prompt/model admission.

## Performance priorities

For a live reply:

```text
latency = acceptance + context reads/serialization + provider queue/load
        + prompt processing + reasoning before visible text + visible decoding
        + final commit
```

The current intake adds an entire extraction call before the first visible response. Removing it is the clearest latency improvement. Therapy already uses one call: avoid adding classification, retrieval-model, or memory-writing calls per turn. SQL and prompt construction should be measured, but model processing is the likely dominant cost.

For completion:

```text
user-visible acceptance = one local transaction
time until READY = model load/queue + one full-session review + validation/commit
```

The target removes a serial update call and most unused assessment output. Full-session coverage may increase review input versus today's partial projection, so net speedup must be measured. Do not quote a 2× gain from call count alone.

Optimization order:

1. Remove redundant calls and unused output fields.
2. Bound generated text, schema complexity, and repeated context.
3. Disable/bound reasoning for conversation when the chosen model/runtime supports it and admission shows acceptable responses. Review reasoning may be useful; benchmark with identical fixtures.
4. Keep stable instructions early in prompts so runtime prefix caches can help; Jung does not own a KV-cache layer. Cache only immutable style text/schema objects in process if useful.
5. Measure first visible token, total reply, review wall time, tokens, corrections, and failure rate. Compare the same prompts/configuration; separate model loading from steady-state inference.
6. Consider a second model only with measured benefit and memory headroom. Weights, active context/KV cache, and concurrent inference compete on one laptop.
7. Batch or overlap independent eval cases only when measurements justify it. Default product inference remains sequential; patient turn N+1 cannot begin before therapist turn N, and session N+1 should not outrun its review.

There is no initial need for a request scheduler, precomputed embeddings, response cache, generic provider fallback, or background summarization. A small profile switch and a shorter prompt can be more valuable than another orchestration layer.
