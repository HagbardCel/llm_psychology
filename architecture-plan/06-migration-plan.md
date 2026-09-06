# Migration plan and simplification ledger

## Execution rules

Start from the actual baseline described in [current state](01-current-state.md), not from a historical phase plan. Before implementation, rebase the inventory onto the then-current main branch and inspect local changes. Create a scoped branch following the repository's branch convention. Do not overwrite unrelated work, run against a real patient database, or reinterpret old eval artifacts as instructions.

Each phase below is one coherent integration unit, normally a PR. M4 needs several scoped commits within one branch because it removes interconnected product concepts. There are no compatibility routes, dual writes, hidden feature flags selecting old/new processors, or migration adapters. The target is a breaking change in the existing `/api/v1` namespace; console and tests change in the same phase.

For every integrated phase, run `make check`. For documentation edits, also run `make docs-links`. Focused commands below are additional checks, not replacements. Run live surfaces only for the property the change can invalidate, respecting any explicitly retained experiment preconditions. If a suitable configured server is unavailable, report **not run**, and do not describe the relevant model-dependent acceptance criterion as proven.

Use synthetic data and an isolated data directory for development. Historical real-model evidence can be reused only where model, prompt, schema, relevant transport behavior, and measured property remain applicable. A new schema/prompt cannot inherit semantic admission merely because the old implementation passed.

## M0 — Establish a small comparison baseline

**Goal:** preserve useful requirements and know what the migration changes before deleting mechanisms.

**Current components affected:** this plan, canonical documentation, `tests/README.md`, `evals/README.md`, current hard cases and saved outcome documents. No production change.

**Target change / implementation:**

1. Record revision, dirty state, Python/SDK versions, enabled model profiles without secrets, and deterministic test outcome.
2. Turn the hard-contract disposition table in [observability and evaluation](05-observability-and-evaluation.md) into the implementation PR's checklist. Identify explicitly retired intermediate contracts.
3. Select 6–10 synthetic examples covering useful sparse intake, clear denial, a later correction, historical/current attribution, prompt injection, no plan change, plan adaptation, and non-conversation closure. Reuse existing scenario text where suitable.
4. Define a small human-review rubric: no unsupported patient facts; meaningful response to current input; visible uncertainty; useful next-session direction; no broadening of a safety denial; no obvious method/safety conflict. Use the same input to compare review shapes.
5. Do not rerun closed Phase 8 experiments merely to establish a clean-looking baseline. Reuse their reports only for the historical questions they measured.

**Code expected to disappear:** none yet; do not start broad file moves.

**Tests:** baseline `make check`; verify the selected fixtures do not contain real patient information.

**Live validation:** optional one current-model replay if no applicable frozen output exists for a necessary comparison. No new speed/quality assertion without a valid baseline. An unavailable model does not block writing the implementation plan, but it does leave later admission pending.

**Documentation:** plan/status notes and the contract checklist; canonical behavior remains current.

**Exit:** exact baseline and retained/changed/retired claims are recorded; each expensive future run has a named purpose and budget.

**Dependencies:** none.

## M1 — Make evaluation evidence direct and small

**Goal:** decouple test evidence from the production diagnostic schema before replacing observability or therapeutic processing.

**Current components affected:** `evals/intake_risk_denial_evidence.py`, `evals/test_intake_clear_risk_denial.py`, `evals/simulation/intake_forensics.py`, relevant sections of `simulation/audit.py`, `harness.py`, `runner.py`, smoke evidence helpers, and their deterministic tests.

**Target change / implementation:**

1. For Category C, capture outgoing SDK/HTTP requests in a test-local hook and the accepted typed extraction at the gateway boundary. Keep an ordered attempt list scoped to this test invocation. Capture before/after intake records directly.
2. Preserve its present assertions, including no invented medical-urgency dimension, exact submitted-request identification where the frozen contract requires it, and cleanup/evidence failure reporting. Do not yet change the production intake algorithm.
3. Replace trace-event correlation and replay with direct observed values. No duplicate implementation of merge rules in the evidence checker. The product function's actual result is compared against the test's expected facts.
4. Reduce the simulation audit to API results, durable source relationships, and a small readable failure summary. Withdraw its broad intermediate intake reconstruction as a diagnostic feature; retain exact evidence only in tests which explicitly assert it.
5. Keep one journey runner and strict failure outcomes. No permanent production observer callbacks added solely for evals. Existing gateway injection and the SDK's injectable HTTP client are sufficient seams.

**Code expected to disappear:** generic extraction-attempt correlation, reconstructed intermediate path matrices, duplicate merge replay, large Markdown forensic rendering; retain reusable small private-file helpers only until M2 relocates them.

**Tests:** owning `tests/unit/evals` and `tests/integration/evals/test_simulation_journey.py`; missing/duplicate capture, cancellation, raw-invalid response, evidence write failure, and simultaneous primary/cleanup failure. Confirm the test counts actual physical requests and cannot pass with absent evidence.

**Live validation:** one retained Category C run on the configured current fixture when its exact-evidence contract requires execution; no full journey or semantic matrix solely for artifact refactoring. Do not reuse an old artifact to claim the new recorder captured this run.

**Documentation:** `evals/README.md`, `tests/README.md`, safety documentation's artifact descriptions, any retired simulation-forensics reference.

**Exit:** hard assertions still hold at their proper boundary; no hard test needs production trace-v5 replay; malformed/incomplete evidence fails explicitly; ordinary simulation output is smaller and understandable.

**Dependencies:** M0.

## M2 — Replace bespoke diagnostics with standard logging

**Goal:** one operational logging path, private payload capture when requested, no automatic database duplication.

**Current components affected:** `diagnostics.py`, `_application/diagnostics.py`, `llm/tracing.py`, provider adapter recording branches, composition cleanup/snapshot code, API request context, logging setup, config, diagnostic tests and eval capture wiring.

**Target change / implementation:**

1. Introduce one small logging setup/context module using stdlib handlers and a JSON formatter. Emit INFO application transitions even without full capture.
2. Move logical and physical call logging into the concrete gateway/correction boundary; remove `ObservedLLMGateway`. Keep task/profile metadata explicit and cancellation-safe.
3. Replace repeated recorder arguments in application/store-call helpers with ordinary contextual log calls. Do not introduce a generic tracing decorator.
4. Use a separate non-propagating private payload handler, explicit capture flag, and size/incompleteness limits. Extract the useful existing secret redaction and private-file behavior rather than rewriting them carelessly.
5. Replace arbitrary exception-string/traceback output with safe metadata and stack frames; preserve detailed payload evidence only in the opted-in path.
6. Remove automatic snapshot on runtime teardown. Provide a small explicit SQLite-backup command and let evals inspect their own database. Simplify teardown only after preserving primary-error and cancellation semantics.
7. Have report timing aggregation consume direct per-run attempt records or structured metadata, without preserving an entire compatibility event vocabulary.

**Code expected to disappear:** `DiagnosticRecorder`, `DiagnosticSink`, `ObservedLLMGateway`, command recorder façade, production trace schema/version/sequence mechanics, automatic snapshot lifecycle, duplicate attempt recording/error ladders. Keep useful redaction and cleanup primitives.

**Tests:** metadata emitted with capture disabled; context isolation for concurrent calls; credentials from both profiles redacted; no patient/provider exception body in ordinary DEBUG; private permissions; logging failure cannot change chat/review result; capture incomplete marker; explicit export consistency; primary and cleanup errors preserved. Update API/console observability integration tests to behavioral assertions.

**Live validation:** not required for unchanged therapeutic behavior. A tiny synthetic capture on an available endpoint can validate public raw-response integration if mocks do not cover a provider-specific behavior; do not run a full behavioral suite for log formatting.

**Documentation:** architecture, development/config example, safety/data handling, tests/evals ownership.

**Exit:** an unexpected timeout can be located through ordinary logs without enabling payload capture; no trace-v5 consumer remains; full database copies happen only through explicit export/eval need; `make check` passes.

**Dependencies:** M1. Replace consumers before deleting their old event source.

## M3 — Make the local-model boundary explicit and bounded

**Goal:** predictable generation attempts and a small separation between endpoint capabilities and task policy.

**Current components affected:** `llm/gateway.py`, `policies.py`, `openai_compatible.py`, `structured.py`, `config.py`, `composition.py`, adapter/settings/composition/smoke tests, operator examples.

**Target change / implementation:**

1. Separate runtime profile/model/capability fields from task policy. Keep current phase task names until M4 removes their owners; do not add a registry or routing configuration.
2. Resolve one shared profile by default; make a second endpoint explicit with endpoint-scoped credentials. Reuse clients where transport/credentials genuinely match. Reject unknown options and overrides of application-owned request fields, including alternate output-cap spellings.
3. Add finite task output caps, an outer logical-call deadline, transport read/connect timeouts, and explicit terminal finish checks. Structured correction consumes the same total deadline. Stream close/drain remains mandatory.
4. Admit SDK public Pydantic parse for `json_schema`; remove Jung's strict-schema transformation/double walk if this path passes exact-request and invalid-output tests. JSON-object/prompt modes must receive the schema and use strict complete-object Pydantic validation. Keep no private SDK imports and no hidden retry layers.
5. Make correction feedback bounded and safe, with no requirement to paste the invalid response back. Only schema/semantic errors qualify; protocol/truncation/refusal/cancellation do not.
6. Add the simple whole-request cost helper and source-independent admission checks. The old phase projections remain until M4, but the outer request can no longer exceed a configured known envelope without a clear failure.
7. Acquire a data-directory process lock before initialization/recovery. Do not confuse this with SQLite transaction locking.
8. Update one readable endpoint/task configuration surface. Remove redundant JSON/environment parsing once no caller needs it; M4 will reduce the six task names to two. Keep temporary task names, not two simultaneous configuration parsers.

**Code expected to disappear:** generic strict-schema conversion/checking, redundant policy/model propagation, credential inheritance branches, repeated JSON parsing helpers, optional unlimited output behavior, duplicated adapter exception ladders remaining after M2. No new retry framework.

**Tests:** focused `tests/unit/llm`, settings and role-composition tests, application/API interrupted-stream tests; confirm exactly one/two physical calls, no third call, slow-drip total deadline, deadline exhaustion before correction, valid JSON with length finish, blank text, refusal, missing terminal, output-only reasoning, stream-close failure, wrong-origin credentials, second-process rejection, and public raw-capture behavior.

**Live validation:** `make smoke-local-llm` when an admitted fixture is available; structured-mode changes also require the relevant existing deterministic tests and `make evals` on that fixture. Include the actual review/assessment schema in compatibility checks; a trivial `{ok:true}` schema is insufficient. Run both distinct profiles if there are two. No therapeutic-quality claim follows from smoke.

**Documentation:** architecture, development, `.env.example`/new TOML example, safety/data handling, evals/test ownership. Document that timeout is total logical-call time as well as transport timeout.

**Exit:** failure/attempt semantics match the target; admitted endpoint behavior is recorded; no schema/helper private API dependency; model profiles expose known capacity; SDK parse deletion is justified by passing tests, not assumption.

**Dependencies:** M2. Public SDK compatibility is a bounded implementation gate; if it fails, keep only the necessary direct-create branch and document why, rather than adding a provider framework.

## M4 — Cut over the therapeutic and persistence model

**Goal:** remove the old intake/assessment/two-pass/operation architecture in one working vertical change.

**Current components affected:** all four phase packages, `domain/models.py`, `domain/session_artifacts.py`, application/inputs/chat/operations, `workflow.py`, store/schema, API contracts/routes/mapping, console, styles, config task list, hard evals and journey setup.

**Target change:** implement [target workflows](03-target-architecture.md) and [five-table model](04-data-and-context-model.md) together. There is no period on the integrated branch in which an old and new processor both own intake or review.

**Implementation commits within this one integration unit:**

1. **Define final domain documents and SQL.** Slim plan/review shapes; explicit patient input metadata; source selections with origin; session-owned review status/attempt/error; frozen session preferences and capacity metadata. Bump `SCHEMA_VERSION` from the then-current value (currently 7). Remove `operations` and intake extraction JSON. Foreign-key and partial-index tests land with DDL.
2. **Implement transactional use cases.** Create intake, finish intake/end therapy, claim/fail/retry/complete review, persist chat and input metadata, and read a consistent snapshot. Use expected starting plan and review attempt guards. Store API remains concrete; no repository or work-item abstraction.
3. **Implement conversation and one review.** Use shared text streaming for intake/therapy. One review draft with explicit section validators and source-handle resolution. Initial review requires a plan; later review accepts null. Compare full bounded replacements for no-op detection. Do not durably duplicate accepted plan content in the review.
4. **Implement whole-request context and capacity.** Full session for review; minimal bounded plan/handoff; reserved active source references; recent contiguous complete exchanges for conversation. Validate handoff-source fit before commit and prospective full review before accepting a turn. M5 improves search, not these correctness guarantees.
5. **Reuse cancellation/work ownership.** Adapt the current owned task to session identity and attempt; preserve drained SQLite writes. Recover stale running work as interrupted/failed; resume pending accepted work; expose explicit retry/resume. Do not replace correct commit-race handling with a casual background task.
6. **Update API and console atomically.** Remove style-ranking/assessment projections and `/operations/current/retry`; use `/sessions/{id}/review/retry`. `POST /sessions/{id}/end` closes either intake or therapy under the documented preconditions. Add typed user self-report/explicit recall metadata to chat; include it in durable idempotency. Expose full review/source links on history. Provide user-controlled finish intake, visible review failure/retry, capacity warning/draft preservation, and always-available help.
7. **Remove old responsibilities.** Delete extraction/completion/merge code, assessment models/validators/prompts, the second review call and resolved-evidence/update packing format, operation entities/result JSON, unused style-assessment instructions, unused prompt opening branches, and obsolete task settings. Target has only conversation/review task policies.
8. **Update tests and contracts before integration.** Retire old intermediate assertions explicitly; add their target replacements, including negation selection and next-context inclusion. Update simulation setup to use explicit finish/style preference. Correct canonical documentation discrepancies noted in current state.

**Development database handling:** stop every process using the selected disposable data directory; remove only that development database and its WAL/SHM sidecars, then initialize the new schema. Test with temporary directories by default. If a developer wants to preserve a local historical database, keep an untouched private export for historical inspection; there is no import/migration compatibility project. Do not reset the user's normal data directory as an incidental test action.

**Code expected to disappear:** the entire nested intake extraction/materialization/merge/completeness pipeline; per-style assessment output and coverage validation; sparse `PlanPatch` merge logic; `ResolvedSessionAnalysis`, intervention evidence atoms and `update_context.py`; generic operation lifecycle/result types; multiple workflow stages and their mapping/console paths; obsolete diagnostic/eval assertions tied to those concepts.

**Required deterministic cases:**

- Sparse intake can finish explicitly; zero-message intake cannot; no model marks intake complete.
- Explicit self-report dimensions are retained exactly; absent/declined/unsure are not denials; metadata changes conflict under the same message ID.
- One text call per normal turn; one review call plus at most one correction per completed conversational session.
- Initial intake review can create plan from user-only source; no-content therapy creates no new strategy or unsupported interpretation.
- Latest useful handoff survives an empty review; a preceding unanswered patient source remains available.
- Full-session review coverage; capacity rejection before accepting a new user; current text appears once; no source text truncation.
- Foreign/hidden/incorrect-role citations fail; historical sources cannot be cited as current-session events.
- Review+references+optional plan+completion commit together; injected failure at each write leaves no partial artifacts.
- No-op review keeps plan version; method change is handled explicitly; completed plan/review content remains immutable.
- Interruption/retry and late worker completion cannot duplicate results or advance a newer attempt.
- Console/API happy path, source inspection, user-visible failure, busy rejection, and uncertain-delivery reconciliation.

Run owning store, application, API/OpenAPI, context, adapter, and console tests, then `make check`. Replace tests of deleted implementation details; preserve the underlying behavioral assertions.

**Live validation:** this phase changes therapeutic behavior and prompts, so it needs the adapted `make evals`, a focused `make eval-report` subset with human review, and one short two-session real-HTTP journey when configured. Admit the compact review on the selected fixture using initial plan, no-change, correction/negation, adaptation, and injection cases. Require each case to complete within the declared attempt/output budget and satisfy its hard source contracts. A failed case is not averaged away. Do not run a full multi-style longitudinal matrix by default.

**One-call review decision gate:** compare the fixed cases against useful prior output. If the intended reviewer repeatedly cannot produce a useful valid compact review after one correction, inspect schema/prompt/capacity first. If the compact design remains inadequate and a measured two-call design addresses the failure, revise D2 before integrating. Never ship two alternative production processors behind a flag to avoid deciding.

**Documentation:** all six canonical docs, `tests/README.md`, `evals/README.md`, config examples, root usage instructions, and `AGENTS.md` restatements. Product behavior changes become canonical here; this planning directory remains a decision history, not another competing product contract.

**Exit:** setup → intake → first plan → therapy → one review → next therapy works over HTTP; no obsolete production phase owner remains; the five-table schema and source links are verified; failure paths preserve state; deterministic gate passes; model-dependent acceptance is either evidenced or explicitly pending and not claimed complete.

**Dependencies:** M3. This phase contains one deliberate schema reset, not a chain of compatibility upgrades. Do not split its database/flow owners into independently merged incompatible PRs.

## M5 — Finish historical retrieval and inspection

**Goal:** useful continuity at tens/hundreds of sessions without loading every review or adding RAG infrastructure.

**Current components affected:** new context functions, SQLite read queries, source/history API/console, deterministic context/session-history fixtures. M4 already establishes correct mandatory-source and full-review behavior.

**Target change / implementation:**

1. Replace any transitional broad session listing with dedicated latest-handoff, recent-exchange, candidate-reference, and source-read queries.
2. Implement parameterized lexical candidate selection and deterministic recency/ranking with a small candidate limit; bounded explicit recall IDs always take precedence if they fit.
3. Include source dates, roles, session identity, and current/historical labels. Preserve a later correction and original source, without synthesizing a patient-fact record.
4. Complete source navigation from note/plan origin in the console. Page session lists with an ordinary cursor/limit where useful.
5. Log omission counts/reasons and cost estimates; no persistent prompt snapshot or summary table.
6. Measure query/serialization cost at 100 sessions. Add an ordinary SQL index only when the actual query plan warrants it. FTS/embeddings remain outside this phase unless the fixed recall fixture demonstrates a requirement and D6 is amended.

**Code expected to disappear:** broad `list_sessions`/full-review loading in prompt input assembly; residual old projection helpers; redundant private history formatting. Do not add ranking interfaces for hypothetical future retrievers.

**Tests:** synthetic 100-session store/context fixtures; older relevant versus newer irrelevant source; repeated wording deduplication by ID rather than text; conflicting dated reports; language mismatch behavior; explicit source recall; oversized mandatory sources; no-content handoff continuity; API pagination/source lookup.

**Live validation:** one fixed two-session handoff replay or selected longitudinal report cases when context changes can affect behavior; run the applicable hard negation/injection contracts. Reuse M4's provider compatibility evidence when wire/schema/model behavior is unchanged. An expensive 100-session live run is unnecessary to test bounded SQL loading.

**Documentation:** architecture context description, database query/index ownership, API source inspection, development console commands, tests/evals ownership.

**Exit:** active request construction uses bounded candidate sets; source inspection works; fixed recall/negation cases pass; measured local query work is small relative to inference; no generated interpretation is promoted into factual memory.

**Dependencies:** M4. No schema reset should be necessary if M4 implements the specified source/reference fields.

## M6 — Consolidate, retire, and accept

**Goal:** leave one understandable architecture and a small verification surface.

**Current components affected:** obsolete phase/eval imports and helpers, closed benchmark executables, `Makefile`, workflow CI, documentation indexes, architecture tests, examples, generated local artifacts.

**Target change / implementation:**

1. Remove closed experiment executables such as `phase8d/patient_benchmark.py` from maintained tooling. Retain outcome documents with exact historical revision/run references. Do not silently delete private evidence directories.
2. Consolidate the behavioral report into selectable reusable cases; remove obsolete matrix/projection scaffolding and remaining forensic reconstruction. Keep scenario diversity without requiring all combinations on every run.
3. Simplify `Makefile` around deterministic check, configured-model admission, selected model contracts, selected qualitative replay, and one journey command. Retain recognizable existing command names where practical.
4. Remove dead imports, old config variables, obsolete schema/task names, and tests that freeze deleted layouts. Keep cancellation, API, SQL, provenance, and trust-boundary tests.
5. Reconcile canonical documents and `AGENTS.md` to the implemented target. Mark this plan implemented or superseded with revision links; do not leave future-tense promises looking like current contracts.
6. Read the main flow from API → application → context/prompt → model → store as a new developer. If understanding requires a new registry, event model, or hidden fallback, simplify it.

**Code expected to disappear:** leftover benchmark arms, old forensic renderers, compatibility comments/helpers, unused style assessment text, dead tests/fixtures. No feature is removed merely because its file is long.

**Tests:** complete `make check`; focused tests for any cleanup that changes runtime behavior; validate documentation links including this planning directory. Confirm no production imports from eval/test code and no private SDK API imports.

**Live validation:** reuse M4/M5 frozen evidence if no measured property changed. Run a new short journey only if integration changes invalidate it. Record profile/model/prompt/schema/configuration for every retained admission result. Do not require a long journey solely as ceremonial finalization.

**Documentation:** root and docs indexes, all current command/config examples, test/eval ownership, historical phase labels.

**Exit:** target acceptance checklist below is complete; no dual architecture or obsolete supported contract remains; counts/maintenance assessment show actual simplification; all remaining live-validation gaps are explicit.

**Dependencies:** M5.

## Simplification ledger

Ranges below are rough review budgets, not estimates from an implemented diff. New/deleted code counts include comments/helpers and may move as implementation proceeds. Do not sum overlapping file inventories or manufacture deletions to hit a target. At each PR, replace estimates with the actual diff and explain growth.

| Phase | New concepts | Removed concepts | New production code | Deleted production code | Dependency change |
|---|---|---|---|---|---|
| M0 | None | None | None | None | None |
| M1 | Test-local direct capture | Trace replay/correlation as general proof machinery | Ideally none | None expected | None; roughly 1–2k net eval-line reduction is plausible |
| M2 | Standard log fields; explicit export | Recorder lifecycle/schema, wrapper gateway, automatic snapshot | About 200–350 lines, reusing redaction | About 900–1,300 across recording/wrapping/plumbing | No new dependency |
| M3 | Explicit endpoint capability and total-call budget | Mixed model/task settings, custom schema walks, unlimited output | About 150–300 | About 250–500 beyond M2 | More use of existing SDK; no added package |
| M4 | Compact unified review; session-owned work; explicit intake finish; source self-report metadata | Extracted intake slots, inferred completion, ranked assessment, two-pass review, sparse plan patch, operations | About 900–1,800 | About 3,000–4,500 | No added package; historical task settings removed |
| M5 | Small candidate query and explicit source recall | Whole-history prompt loading, remaining elaborate packing | About 150–300 | About 150–400 | No vector/embedding dependency |
| M6 | None | Closed benchmark machinery and obsolete supported paths | Near zero | About 100–300 residual lines | No runtime removal required; dev dependencies retained |

M4 introduces genuinely useful product behavior and therefore is not “deletion only.” The new review capacity check prevents partial-session interpretation; explicit source metadata prevents model-authored provenance; session work state preserves restart reliability. These additions earn their cost. If its net result grows substantially, first examine whether duplicate plan/handoff representations, compatibility adapters, or overlarge review schemas slipped in.

The expected outcome is a several-thousand-line reduction in production and a substantial reduction in eval infrastructure. This is directional, not a promised percentage. API/client, SQL integrity, and cancellation code intentionally remain. Seven runtime dependencies can remain seven; a leaner architecture need not have fewer packages when those packages already do useful work.

## Target acceptance checklist

- [ ] One running backend per data directory; one database; no live-model/real-data use in deterministic tests.
- [ ] A new developer can identify conversation, review, source truth, current strategy, and next-session context without understanding historical phases.
- [ ] Intake can finish with uncertainty; review creates one provisional plan for the chosen method.
- [ ] One normal text call per user turn; one bounded review call plus at most one correction; physical attempts and deadlines tested.
- [ ] Current patient text, explicit self-reports, older wording, and derived hypotheses have distinguishable owners.
- [ ] A later correction remains visible without altering earlier history or being rejected by confidence/length heuristics.
- [ ] Review sees the entire source session; accepted handoff anchors fit; session capacity has a usable UI path.
- [ ] Failed/cancelled/retried work never creates a partial applied plan, duplicate source relationships, or false successful stream.
- [ ] Ordinary logs identify failed requests/calls without patient payloads; exact capture/export is deliberate and private.
- [ ] Hard model cases cover the target source/negation/instruction contracts; qualitative review and one applicable short journey support continuity.
- [ ] No old task modes, operation result owners, duplicate plan recommendations, or forensic event-contract dependencies remain.

## Deliberate final simplification pass

| Question | Final decision after review |
|---|---|
| Can a component disappear? | Assessment and extraction disappear; retrospective update disappears; generic operation record disappears only after one review per session is established |
| Can two concepts become one? | Intake/therapy share conversation; initial/later analysis share review; work identity is the source session |
| Is information duplicated? | Remove durable replacement-plan content from the review; selection rows own memory selections; messages own wording; keep reference links with distinct purposes |
| Is derived material pretending to be truth? | All review and plan content stays derived; provenance validates identity, not semantic truth; explicit self-report metadata comes only from user input |
| Can logging replace audit machinery? | Yes for operation; exact test evidence stays small and test-owned where explicitly required |
| Can code replace a model call? | User completion/style choice and deterministic no-content handling replace model bookkeeping; conversation still benefits from natural language |
| Can one call replace two? | Recommend compact review, subject to specified admission; no assumption that structural validity establishes quality |
| Is one call overloaded? | Remove redundant analysis fields and per-style plans; validate note, sources, handoff, and plan independently; reopen D2 on demonstrated failure |
| Is a new framework necessary? | No; existing SDK, SQL, asyncio, logging, Pydantic, and HTTP stack suffice |
| Does history growth require RAG? | No; preserve history, bounded candidates, active anchors, and explicit recall; measure misses before adding retrieval machinery |
| Is another live evaluation necessary? | Only if a changed property invalidates prior evidence; 100-session storage/selection behavior is deterministic |
| Is the one-laptop constraint exploited? | Single work owner, local lock, no distributed jobs, no provider router, no inference orchestrator |

## Planning deliverable validation

This section records checks of the **documents**, not validation of the future runtime. Production and local model configuration were not modified; no database reset or live model evaluation was performed for this planning task.

`make docs-links` passed. `make check` passed: format/lint/documentation checks, **1,037 unit/integration tests**, and **3 console tests**. The unchanged suite emitted one warning that a `run_local` coroutine was never awaited; that warning is recorded rather than repaired in this documentation-only task.

The additional plan-specific check also **passed** using `md-link-checker==1.10 --no-urls architecture-plan/*.md`, after replacing four section-link forms that this checker treated as file paths. Local source links and Markdown code-fence balance were also inspected; `git diff --check` passed. No new runtime tests were added for documents. Model latency/quality improvements remain hypotheses until the migration's named experiments are executed.
