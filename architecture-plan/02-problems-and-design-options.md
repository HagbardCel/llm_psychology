# Problems, design options, and decisions

The strongest existing choices are explicit SQL, atomic commit boundaries, source-message ownership, one application writer, and request-owned chat. The largest opportunity comes from reducing the number of things Jung asks models and evaluation tools to maintain.

The earlier leanness assessments mostly optimized within an agreed feature set; Edition 3 explicitly kept the supervisor pipeline and HTTP boundary fixed. This plan keeps HTTP after reconsidering its alternative, preserves retrospective learning, but replaces the current supervisory call split and intake gating. Those earlier small consolidation budgets are not a ceiling on a redesign that intentionally changes product mechanisms.

## Architectural problems

### P1. A model-maintained intake record controls access to therapy

**Current behavior:** extraction → provenance materialization → nested merge → completion policy → another model response. Completion depends on informative/addressed states and turn thresholds. Intended prompt targets become `direct_ask` metadata; scalar replacements depend on confidence and value length. See Flow A in the [current-state analysis](01-current-state.md).

**Underlying requirement:** understand the presenting concern, invite goals and relevant background, offer safety questions, avoid endless intake, and preserve what was actually disclosed.

**Problem:** the application is partly testing whether a local model can populate its bookkeeping scheme. A perfectly understandable denial or correction can fail extraction, lose a merge comparison, or leave the user looping. Quote containment proves that a substring occurred, not that the extracted value faithfully represents it. The confidence field supplies no reliable authority for rejecting a newer statement. Complex forensic code exists partly to explain these intermediate failures.

**Keep the requirement?** Yes. Neither comprehensive slot coverage nor a particular number of turns is independently justified by the stated product intent.

**Simpler alternatives:** a patient-completed questionnaire; free intake conversation with explicit completion; a much smaller extractor which only recommends the next question. The last option still puts extraction latency and failure in the live path.

**Direction:** conversational intake with an explicit **finish intake** command, a short displayed orientation checklist, and direct self-report controls when typed answers are useful. Retain raw wording. Review identifies unknowns and proposes clarification; it does not turn unknowns into a gate. No minimum beyond a nonblank patient contribution, no maximum-turn completion heuristic, and no inference-based readiness label.

### P2. Assessment generates alternatives the application never uses

**Current behavior:** one full initial plan and numerical suitability score per packaged style, exact catalog coverage, score sorting, immutable subsequent style choice. Some docs describe a different design.

**Underlying requirement:** a coherent method chosen with user agency and an initial therapeutic direction grounded in intake.

**Problem:** most generated plans are discarded. Scores look more precise than their evidence warrants. Catalog edits can invalidate interpretation of historical assessments. The compulsory style-selection stage exists because assessment produces a catalog-shaped result.

**Keep the requirement?** Keep user choice and a meaningful style effect. Drop generated ranking and frozen lifetime selection.

**Alternatives:** generate only a recommendation and then a selected plan (two calls); generate a style-neutral plan then adapt live; choose preference before assessment and generate one plan.

**Direction:** start intake with visible English/supportive defaults and plain style descriptions. Preference edits before the first accepted message update intake's snapshot; later edits apply to future sessions and their reviews. Review produces one plan for its session's method. No separate SETUP gate, automatic style switching, or unsupported claim that one packaged method is clinically best.

### P3. The second retrospective call has a costly authority boundary

**Current behavior:** analysis gets a selected transcript; validators check citations; resolved full turns and selected interpretive fields become a second prompt; update generates handoff and plan patch.

**Underlying requirement:** learn from a completed session without inventing events, and adjust future direction.

**Problem:** two serial calls, two correction opportunities, two prompt projections, and an intermediate format. Validating citations cannot make the whole analysis authoritative. The second call may not see source material needed to challenge an inference. Its failure forces a later operation retry to repeat analysis.

**Keep the requirement?** Absolutely. Separate validation responsibilities remain useful; separate LLM invocations are a hypothesis, not a necessity.

**Alternatives:** one call; two calls with a durable analysis checkpoint; one free-text review plus another structured planner; one call whose whole result is stored as undifferentiated memory.

**Direction:** one compact structured review with independently validated review notes, source selections, handoff, and optional replacement plan. Do not store an undifferentiated document as factual memory. Do not persist a checkpoint merely to retain the current call split.

### P4. Context packing is sophisticated but misses more fundamental guarantees

**Current behavior:** rich/minimal candidate searches, different character limits by phase, current text exempt from the therapy historical limit, content-only historical sources, optional memory last, and partial-session retrospective selection.

**Underlying requirement:** fit local context windows while maintaining relevant, trustworthy continuity.

**Problem:** character ceilings do not bound the complete request, schema, or reasoning/output reserve. Critical historical evidence can be starved by recent dialogue. Whole-turn omission prevents quotation damage but can still remove context needed to interpret adjacent turns. A review may appear to describe a whole session it only partly saw. Historical wording lacks dates in prompts, inviting temporal confusion.

**Keep the requirement?** Yes. Preserve permanent history separately from prompt inclusion.

**Alternatives:** full replay; rolling summaries; vector retrieval; deterministic selection with bounded documents; splitting large sessions into multiple review calls.

**Direction:** bound the whole request, reserve small continuity/evidence allocations, include dates and source handles, and pack complete exchanges. Review sees the full completed session. The application limits the size of an active session to a reviewable envelope and helps the user continue in a new session. This trades unlimited session length for far less review machinery. It does not delete history. Revisit chunked review only if realistic sessions cannot comfortably fit.

### P5. Durable interpretation and debug evidence have uneven owners

**Current behavior:** assessment lives in operation result JSON; therapy review lives on sessions; applied plan also duplicates a recommendation in the review. Model name/prompt versions exist for therapy review but not a uniform generation record. Memory selection provenance must be recovered through review citations.

**Underlying requirement:** understand what was said, what was concluded, what changed, and why.

**Problem:** product interpretation follows two persistence routes; maintaining an operation entity partly compensates for phase distinctions. The reviewer recommendation/applied-plan relationship can diverge in future changes. Log forensics is asked to recover some relationships better represented directly in product state.

**Keep the requirement?** Yes. Product-source links are not optional observability.

**Alternatives:** event sourcing; generic artifact table; all state in a mutable profile; ordinary tables with compact JSON documents.

**Direction:** sessions own all reviews, plans own applied strategy, memory-reference rows own selected source links, and review status lives on its source session. Keep small generation provenance on generated product artifacts. Do not store successful plan content twice.

### P6. Detailed normal debugging requires a bespoke capture mode

**Current behavior:** commands/transitions go through recorder helpers; logical calls through a gateway wrapper; provider attempts through adapter events/callbacks. Debug runs automatically copy the whole database. Some ordinary exception paths are less privacy-aware than the diagnostic redactor.

**Underlying requirement:** reconstruct unexpected outcomes, including concurrent model attempts, without routinely exposing patient material.

**Problem:** routine observability is fragmented. Debug schema evolution and exact forensic consumers make instrumentation expensive to change. A full database copy is disproportionate to many failures. Generic exception stringification is not redaction.

**Keep the requirement?** Yes; reduce the means.

**Alternatives:** OpenTelemetry plus a tracing service; one bespoke event system for everything; standard Python logging plus private payload capture.

**Direction:** standard logging with context variables, correlation IDs, safe exception frames, duration/usage fields, rotating local files, and one opt-in payload logger. Explicit backup/export. Evaluation evidence is test-owned and strict only where a test contract requires it.

### P7. Local-model capability and task policy are mixed, with incomplete end conditions

**Current behavior:** `ModelPolicy` includes model identity and structured mode. Task caps are optional; finish reasons are observed but not enforced; timeout is SDK-level; credentials inherit independently of endpoint origin.

**Underlying requirement:** run one or two imperfect local models predictably and diagnose incompatibility.

**Problem:** configured mode is not proof of runtime support. A length-terminated response can be treated as complete. The operator cannot reason about a logical call's maximum duration. Another endpoint can accidentally inherit the first endpoint's credentials.

**Keep the requirement?** Yes.

**Alternatives:** provider registry/capability negotiation; many provider-specific adapters; two explicit endpoint profiles and two task policies.

**Direction:** the last option. Verify configured capabilities with a small manual admission test, not automatic mode downgrading. Enforce an outer deadline, valid terminal finish, finite output, and explicit cross-origin credentials.

### P8. Evaluation mechanics have become a large parallel model of the product

**Current behavior:** intermediate intake stages are replayed; provider request digests, trace correlations, checkpoints, and result projections are reconstructed and audited. Closed performance experiments retain executable support.

**Underlying requirement:** show that particular source-integrity and behavior contracts held, evaluate quality, and investigate failures.

**Problem:** much code verifies evidence machinery rather than product behavior. Replaying production merge rules in an auditor can reproduce the same mistake. Exact intermediate contracts also make a product simplification look like a loss of safety even where the intermediate concept disappears.

**Keep the requirement?** Preserve explicit hard claims, human review, and honest failure reporting. Retire intermediate assertions only with a documented replacement or an explicit withdrawal of the obsolete claim.

**Alternatives:** no evals; one huge journey suite; ordinary pytest plus small direct capture at the assertion boundary and occasional journeys.

**Direction:** the last option. A trace is useful evidence, but normal production code need not implement a forensic protocol for hypothetical future auditors.

Phase 10 addressed real correctness problems under its then-current extraction contract: attempt correlation, committed versus observed state, evidence completeness, and provenance. Its evidence remains valid for those historical claims. The lesson from the large forensic surface is to reconsider the product contract that required it, not to dismiss that work or reinterpret its results as admission for the new architecture.

## Candidate architectures compared

| Candidate | Simplicity and maintenance | Continuity / provenance | Robustness, diagnosis, and latency | Judgment |
|---|---|---|---|---|
| Current system plus local cleanup | Low migration risk; retains many phase/evidence concepts | Strong source ownership, but recency-heavy context and inferred intake gates remain | Preserves tested recovery; retains serial calls and fragmented diagnostics | Worthwhile only if current product mechanisms are fixed requirements |
| Plain persisted chatbot | Smallest implementation | Source history survives, but no deliberate review, plan adaptation, or next-session handoff | Easy transport testing; longitudinal quality becomes implicit prompt behavior | Too little product for the stated intent |
| One model-generated response/state object on every turn | One apparent call surface | Couples patient speech and durable state updates in one output | Structured failures interrupt conversation; every turn may mutate inferred memory | Superficially compact, operationally fragile |
| Proposed conversation + retrospective review | Few concrete owners; significant deletion with one breaking cutover | Explicit source/interpretation/strategy separation and deliberate handoff | Tested commit/retry core; standard logs; fewer calls; review-model admission still required | Best balance of the ten stated quality criteria |
| Multiple autonomous agents plus semantic retrieval | Many components, configurations, indexes, and failure paths | Potentially richer recall, with more opportunities for inferred facts to circulate | Higher resource/latency cost; harder causal diagnosis and testing | No demonstrated requirement justifies it now |

These are qualitative assessments, not measured scores. Correctness and testability favor retaining transaction/cancellation mechanisms; code volume and local latency favor deleting redundant model work rather than replacing it with a framework.

## Consequential decision records

### D1. Keep HTTP and explicit SQL

**Problem:** a console-only application could call application functions directly and delete HTTP DTO/mapping/client code.

**Options:** direct console binding; existing local HTTP boundary; multiple services.

**Choice and why:** keep the current boundary. Its cost is real, but it already provides independent console/server operation and a practical end-to-end seam. More importantly, it isolates UI behavior from therapy/persistence and permits replay/inspection without importing internals. Do not build another frontend or another API version for this plan; make one breaking update to `/api/v1` and its console.

**Trade-off:** this is not the absolute fewest-line executable. Preserve DTO separation; do not force domain objects to become wire contracts merely to delete mapping code.

**Revisit when:** the product explicitly commits to a permanently embedded, single-interface program and maintaining HTTP proves a material burden.

### D2. Combine review and planning into one call

**Options:** two serial passes, one compact structured call, an unstructured note followed by extraction.

**Choice and why:** provisionally one call, frozen only after R0 admission. The completed transcript, current plan, and previous handoff supply both analysis and next-step reasoning. Test the smallest consumer-justified draft on 6–10 frozen completed sessions before designing production persistence around it. Validate each section separately in ordinary code and commit together. There is no evidence here that another generated intermediary is an independent clinical check.

**Trade-offs:** larger single output; one invalid section invalidates the whole result; the model may mix interpretation with recommendation. Tight schemas, source labels, and targeted trials are required. Combining calls is not guaranteed to halve elapsed time.

**Revisit when:** any R0 case fails its hard contract or human review identifies material omissions/plan drift within the one-correction budget. Refine the compact schema/prompt first; if a measured two-pass design addresses persistent failures, revise this decision before the cutover. Freeze matched inputs and record failures rather than averaging them away. No production restructuring proceeds on pending admission, and no generic workflow framework follows from a second call.

### D3. One model is the baseline; a second is optional

**Options:** one model for everything; fixed conversation/review roles; arbitrary per-task model routing; separate safety/memory agents.

**Choice and why:** two source-defined responsibilities, resolving to the same endpoint profile by default. A larger review model may improve structured reasoning while a smaller conversation model improves first-token latency. The architecture permits that without requiring both residents or assuming benefit.

**Trade-offs:** a second resident model consumes weights plus KV cache and may contend for memory bandwidth. Switching incurs load time; different models can disagree. The latest review is guidance, not a higher authority over patient text.

**Revisit when:** one measured task requires a distinct capability that neither configured role can provide. A third role needs a named failure and its own cost evidence.

### D4. User-controlled intake completion

**Options:** current inferred slots; deterministic questionnaire; conversational orientation with explicit finish.

**Choice and why:** explicit finish preserves the conversational product and removes structured inference from the live critical path. A short orientation checklist invites concern, impact/course, coping, goals, and safety disclosure without claiming these topics are satisfactorily assessed.

**Trade-offs:** intake can be sparse; the first plan must be provisional and openly identify unknowns. The user loses automatic readiness judgments. Direct self-report controls supplement, rather than classify, free text.

**Revisit when:** a real product requirement establishes mandatory assessment items, validated wording, or a supervised protocol. Then use explicit questionnaire answers; do not resurrect confidence-based extraction as proof of assessment.

### D5. Five tables; session-owned review work

**Options:** keep operations indefinitely; store review lifecycle on the session; add event/artifact tables.

**Choice and why:** after unifying initial and later review, each completed session has exactly one review lifecycle. A session row with status, attempt, and bounded error metadata is enough. Keep one owned asyncio task and cancellation-safe writes.

**Guardrail:** conditional attempt fencing protects atomic commits; it does not justify worker identities, leases, attempt-history tables, or an embedded job framework. Generation provenance stays on the accepted artifact, not in a second work ledger.

**Trade-offs:** adding a second independent durable job per session would require revisiting this model. Moving columns alone is not the benefit; removing operation kinds, result ownership, and extra workflow stages is.

**Revisit when:** the product introduces independently retryable work with a separate result and lifecycle. At that point, a small work table could earn its existence again.

### D6. Source references and simple retrieval before embeddings

**Options:** raw replay, model-authored facts, source-reference selection, SQLite full-text search, embeddings/vector storage.

**Choice and why:** start with active handoff anchors, explicit user recall, then a bounded recent memory-reference pool with deterministic purpose/recency ordering. At roughly five selections per review, 100 sessions supply only about 500 candidate references. Test this baseline before adding term extraction, text matching, or ranking infrastructure. The target does not store extracted biographical facts or a continuously rewritten history summary.

**Trade-offs:** recency cannot automatically find every old relevant event, and a bounded handoff can forget an old concern. Explicit source recall is the immediate remedy. Measure unanchored recall misses separately from mandatory-source correctness; do not imply that preserving a source guarantees its prompt inclusion.

**Revisit when:** R6's fixed 100-session recall set demonstrates a material gap despite anchors and explicit recall. A separate R6b may add bounded parameterized lexical matching and compare the same cases. Consider SQLite FTS5 only if that approach remains inadequate; embeddings need a further demonstrated semantic gap. Neither is a default migration deliverable. [SQLite FTS5 documentation](https://www.sqlite.org/fts5.html)

### D7. Standard logs for operation; small direct evidence for tests

**Options:** enrich the current recorder; a distributed tracing platform; standard logging; no durable logs.

**Choice and why:** ordinary Python logging already supports contextual records, filters, and local rotation. Use those mechanisms for normal debugging. Keep evidence recording in the test performing a hard assertion when it needs an exact request/result or before/after state. [Python logging cookbook](https://docs.python.org/3/howto/logging-cookbook.html)

**Rule:** no operational log consumer may become a correctness dependency. A relationship needed to establish product semantics belongs in SQLite or in the owning test's direct evidence, not a join across log events.

**Trade-offs:** ordinary logs can rotate, fail to write, and cannot independently prove every historical transition. Full replay requires opt-in capture. This is acceptable for operation, not for a hard test that explicitly promises exact evidence.

**Revisit when:** a concrete external reproducibility requirement specifies stronger evidence retention. Scope its artifact and tests to that requirement, not the entire product runtime.

### D8. Use the installed SDK's public structured parsing

**Options:** existing schema transformation/parser; the SDK public `chat.completions.parse`; a new structured-output wrapper; permissive JSON repair.

**Choice and why:** first admit the actual intended llama.cpp and MTPLX builds/configurations against the compact review schema in R0. If both pass, target `json_schema` as the sole production review mode. Keep another mode only for a named required endpoint whose measured incompatibility justifies it; do not preserve three paths for hypothetical portability. This intentionally narrows the current configurable endpoint promise when the canonical docs change at cutover.

In R5, test public SDK parsing with a Pydantic response model against the then-locked SDK. The original inspection found this path in SDK **2.45.0**, with one HTTP post; do not assume that inspection admits a later version. Keep Jung's semantic validator, one explicit correction loop, and disabled SDK retries. The deletion target is Jung's strict-schema conversion and second validation walk, plus unneeded structured modes.

**Trade-offs:** SDK parse errors, refusal, length endings, and raw-response capture must be covered against the locked SDK and intended server. Correction can regenerate from original input plus safe error locations; it does not require echoing an invalid sensitive response. Use public raw-response facilities for opted-in capture, never private SDK schema helpers. Model schema constraints still need compatibility tests.

**Revisit when:** the locked public SDK cannot support the admitted endpoint or expose required failure evidence. Retain a narrowly justified direct-create implementation of the admitted schema path in that case, not an extra mode, framework, or hidden repair service. R0 admits server/schema behavior; R5 separately admits the parsing implementation. Neither gate delegates semantic validation.

### D9. Whole-session review, bounded session size

**Options:** silently omit old turns; chunk-and-merge reviews; durable running summaries; a session size that fits the review model.

**Choice and why:** define one conservative maximum serialized session-source size, bound assistant output and all non-session review sections, and admit only review endpoints that fit the complete envelope. Before accepting a turn, add the candidate patient source and maximum assistant source to the current source-byte count. No per-session capacity JSON, frozen runtime, or reconstructed prospective review request is needed. Warn at 80%; reject overflow while preserving the draft and offering explicit closure. History stays permanently accessible.

The product envelope is independent of the configured retry model. A replacement endpoint must fit the same envelope before it can review accepted sessions. R0 fixes the concrete limits using representative multilingual/long-message fixtures; runtime capacity errors remain explicit failures rather than proof that byte counting is exact tokenization.

**Trade-offs:** very long sessions or unusually small review contexts require an earlier break. Automatic chunk-and-merge has no demonstrated need yet, but may be better than disruptive boundaries if realistic use frequently reaches them.

**Revisit when:** recorded session lengths and user feedback show the limit interferes with ordinary use. Evaluate ephemeral chunk analysis then, with explicit coverage and cross-chunk context; do not silently relabel a partial review complete.

### D10. Keep configuration small after task reduction

**Choice and why:** retain `pydantic-settings`, `.env`, and one `load_settings()` owner. Resolve two small types, `EndpointProfile` and `CallPolicy`, once conversation/review replace six tasks. Use the existing environment-over-dotenv-over-default precedence; no TOML artifact, secret-name indirection, or second parser. Fix cross-origin credential inheritance in R1 without coupling that correctness fix to a settings redesign.

**Revisit when:** the resulting two-task configuration demonstrates a concrete usability problem that a file would solve. Remove responsibilities before choosing new configuration machinery.

### D11. Preferences are metadata, not a SETUP stage

**Choice and why:** initialize the profile and intake together with visible English/supportive defaults. Display name is optional. Preferences can be edited before first input, then are frozen for that session; later changes apply to future sessions. The workflow is `INTAKE → REVIEW → READY ↔ THERAPY`, with completed therapy returning through `REVIEW`.

**Trade-off:** the default language/method is a product default, not an explicit patient choice or clinical recommendation. The console must make defaults and pending changes visible. Reinstate a setup gate only for a demonstrated requirement that cannot be met through editable metadata.

## Dependencies and abstraction ledger

No new runtime dependency is required by the target.

| Existing dependency / considered addition | Responsibility and deletion opportunity | Cost / recommendation |
|---|---|---|
| OpenAI Python SDK | HTTP request/response types, streaming, connection pool, public schema serialization/parsing | Keep; delete bespoke schema processing where public parse is admitted; lock and test behavior |
| Pydantic | Typed input/output/document validation | Keep; deletes hand validation of document structure; never delegates semantic truth |
| pydantic-settings | One validated environment/dotenv configuration load | Keep; simplify to endpoint profiles and call policies after task reduction |
| FastAPI + Uvicorn | HTTP lifecycle/routing/streaming | Keep; no extra service tier |
| HTTPX | Console HTTP and test transports | Keep; avoids custom networking/protocol parsing below NDJSON |
| prompt_toolkit | Async console input | Keep; already removes bespoke input machinery |
| sqlite3 + stdlib logging/asyncio | Transactions, logging, owned work | Already available; no ORM, logging daemon, or new configuration format needed |
| aiosqlite | Async connection worker | Defer: does not eliminate cancellation/transaction ownership; current whole-operation thread bridge is small and sound |
| SQLAlchemy / repository layer | Query mapping | Reject now: little valuable SQL disappears; explicit transactions remain necessary |
| Instructor / agent frameworks / generic routers | Wrapping generation/orchestration | Reject now: semantic validation, explicit corrections, and local runtime policy remain Jung-owned; wrapper adds another behavior surface |
| JSON repair library | Guess malformed output into validity | Reject: changes data without evidence; one correction is easier to explain |
| structlog / tracing platform | Rich logging pipeline | Defer: stdlib plus a small JSON formatter meets current requirements; adopt a formatter library only if it removes meaningful maintained code |
| Embedding library / vector database | Semantic retrieval | Defer pending recall failures; runtime/model/index costs are not justified by history size alone |

The proposed `context` module is pure application code, not a service. The review worker is one owned task, not a queue. Style files are prompt inputs, not plugins. The model protocol exposes only the two call shapes needed for testing. Every new abstraction should meet that standard.
