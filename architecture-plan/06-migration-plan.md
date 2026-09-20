# Migration plan and simplification ledger

## Execution rules

Start from the dated inspection in [current state](01-current-state.md), then refresh the inventory against the actual main revision and local changes before runtime implementation. After Phase 10 closes, carry the planning commit and its revisions onto a dedicated `docs/architecture-plan` branch from main using scoped commits/cherry-picks as needed; do not rewrite shared Phase-10 history. Keep Phase-10 completion separate from the next architecture. Do not overwrite unrelated work, run against a real patient database, or treat old eval artifacts as instructions.

R0 is an admission experiment, not production implementation. R1–R7 are coherent integration units, normally scoped PRs. R2 is a short-lived `feat/architecture-cutover` integration branch with stacked reviewable PRs or individually reviewed commits. Intermediate branches need not be supported releases. Integrate the whole vertical flow into main only when its gates pass. There are no compatibility routes, dual writes, hidden flags selecting old/new processors, or migration adapters. The target makes one breaking update to existing `/api/v1`, with console and tests updated together.

For every integrated change, run `make check`; for documentation edits also run `make docs-links` and the plan-specific link check when this directory changes. Focused checks below are additional requirements. Live validation is change-sensitive: reuse frozen evidence only if model, prompt, schema, relevant transport behavior, and measured property remain applicable. Respect retained experiment preconditions. If a suitable configured server is unavailable, report **not run** and leave its gate pending; deterministic tests cannot establish model admission.

Use synthetic data and isolated data directories. R0 evidence cannot be borrowed from the old schema merely because the old pipeline passed. Conversely, do not rerun closed Phase 8/10 experiments for ceremonial completeness. Their reports remain historical evidence for their original claims.

## R0 — Freeze requirements and admit the compact reviewer

**Goal:** validate the largest architectural hypothesis before restructuring production around it.

**Work:**

1. Record revision, dirty state, Python/SDK versions, model/server builds and launch configuration without secrets, and deterministic baseline. Investigate the recorded `run_local` coroutine warning in a separate focused fix before declaring a warning-free migration baseline; do not suppress it or fold unrelated runtime fixes into this document revision.
2. Inventory surviving and retired contracts using the table in [observability and evaluation](05-observability-and-evaluation.md). Confirm explicit intake completion, full-session review, source ownership, recovery, and hard negation/instruction contracts.
3. Use the consumer inventory in [data and context](04-data-and-context-model.md) to minimize `ReviewDraft` before the spike. Remove model-authored scope; retain distinct ownership for note, handoff, source selections, and applied plan. Freeze prompt/schema versions for each comparison.
4. Select 6–10 frozen synthetic completed sessions covering initial plan, no change, later correction, safety negation without broadening to an unasked dimension, historical/current attribution, plan change, and injection. Include the necessary starting plan, prior handoff, and dated sources. Compare against useful two-pass output on the same source inputs, reusing applicable frozen output or obtaining a bounded baseline when missing. Do not claim matched comparison if the current packer supplied different source material; record coverage differences explicitly.
5. Run an eval-only prototype of the compact review on the intended local reviewer. Capture exact synthetic request/result, physical attempts, validation outcome, and human findings directly. No production processor, schema, configuration, or persistence changes. At most one correction per case; transport/protocol failure is not a validation retry.
6. Admit the intended llama.cpp and MTPLX builds/configurations with the actual compact schema. If both support `json_schema`, freeze it as the sole production review mode. Any alternative requires a named required endpoint and a demonstrated incompatibility, documented before implementation; no silent downgrade or indefinite three-mode support.
7. Freeze a conservative `MAX_SESSION_SOURCE_BYTES`, maximum assistant source size, and bounded non-session/correction/output allowance. Use multilingual, long-message, and many-short-message fixtures, actual server settings, and observed usage/tokenization. The envelope includes mandatory historical sources; it is the same product limit for every admitted review endpoint. Keep the existing conversation byte/token/deadline defaults only if the spike supports them.

**Rubric:** no unsupported patient facts; uncertainty remains visible; useful next-session direction; appropriate provisional or changed plan; historical/current attribution preserved; no broadening of a safety denial or obvious method/boundary conflict. Structural validity alone does not establish quality. Do not add a diagnostic clinical scenario as a new hard safety guarantee.

**Gate:** every case must produce useful valid output within its declared attempt/output budget and satisfy its hard source contracts. Record human comparison findings; a failed case is not averaged away. Fix schema/prompt/capacity and rerun affected cases. If a measured two-pass approach resolves persistent failures, revise D2 and affected target sections before production restructuring. Do not maintain competing production processors behind a flag. Unavailable reviewer evidence leaves R0 pending and prevents the architecture cutover from proceeding.

**Validation / exit:** `make check` for committed eval-only work, relevant deterministic harness tests, completed live admission and human comparison, frozen schema/prompt/envelope and endpoint-mode decisions. No production code is expected to disappear yet. Standalone correctness fixes can still be reviewed independently, but they do not imply architecture admission.

## R1 — Model-boundary correctness only

**Goal:** predictable physical attempts and failure behavior without redesigning soon-to-disappear tasks or evidence machinery.

**Work:** enforce valid terminal finishes for streaming/structured output; finite output token/byte caps; a total logical deadline including the one correction; bounded safe correction feedback; explicit cross-origin credentials; and cancellation/stream closure. Keep SDK retries disabled. Reject provider options that override owned request fields, including alternate output-cap spellings. Preserve accepted user messages and cancellation-safe writes on failure.

Retain current task names, settings shape, parsing modes, and forensic consumers until their owning cutover. Make only necessary dependency cuts so new work does not depend on trace-v5 reconstruction. Do not rebuild Category C direct capture, broadly simplify `intake_forensics.py`/simulation audit, add TOML, or switch SDK parsing here. Preserve existing exact evidence assertions and frozen Phase-10 reports.

**Tests:** exact one/two physical attempts, never a hidden third; slow-drip total timeout; exhaustion before correction; parseable JSON with length finish; missing terminal; refusal/blank/reasoning-only output; response byte cap; stream close/cancellation; wrong-origin credentials; existing application/API interrupted-stream behavior. Run `make check` and `make smoke-local-llm` when configured; changed structured behavior also requires relevant `make evals` under retained preconditions.

**Documentation / exit:** update canonical model-boundary/configuration/error descriptions for the implemented correctness changes only. The existing product still works with explicit failure semantics, and no broad evidence/configuration replacement has been built around old therapeutic concepts. Dependency: R0 for this migration sequence.

## R2 — Breaking therapeutic and storage cutover, reviewed as a stack

**Goal:** land conversation and one admitted review with five-table ownership, correct capacity, and a complete HTTP/console flow.

Review these layers separately on the integration branch; none is independently promoted to a supported main release before the vertical flow passes:

1. **Schema and domain ownership.** Edit `schema.sql`, bump `SCHEMA_VERSION` from the then-current value (7 at the original inspection), and update typed models. Implement profile, sessions, messages, plans, and memory references with foreign keys/partial indexes. Remove operations and intake extraction JSON. Add session review status/attempt/error metadata and explicit message input metadata, but no capacity JSON, runtime freezing, leases, or worker registry.
2. **Transactional use cases and lifecycle.** Initialize profile plus intake atomically with visible English/supportive defaults. Update a session's preference snapshot on edits before its first input; freeze it at first accepted patient message, including unanswered input. Implement explicit finish/end, claim/fail/retry/complete, atomic plan/reference/review commit, and consistent reads. Reuse owned-task cancellation and drained store calls; fence by session/status/attempt. Acquire the data-directory process lock before initialization/recovery. Resume pending work; show stale running work as interrupted/failed for explicit retry.
3. **Conversation, review, and context.** Share text streaming between intake/therapy. Implement the R0-admitted compact review, reference resolution, initial-plan/method-change requirements, and no-op replacement detection. Review every completed-session message. Use the fixed source-envelope arithmetic, mandatory context checks, bounded plan/handoff, and recent complete exchanges. Historical selection starts with active anchors, explicit recall, then recent references with deterministic purpose/recency ordering. No lexical search or prospective full-review reconstruction per turn.
4. **API and console.** Remove SETUP, assessment/style-ranking projections, and `/operations/current/retry`; expose `/sessions/{id}/review/retry`. `POST /sessions/{id}/end` closes intake or therapy under its preconditions. Include explicit self-report/recall metadata in chat idempotency; expose typed review/source links in history. Provide preference/default visibility, explicit finish, review failure/retry, source inspection, capacity warning/draft preservation, and always-available help. Preserve the request-owned NDJSON completion/reconciliation contract.
5. **Delete owners and replace surviving contracts together.** Remove intake extraction/materialization/merge/completeness, ranked assessment, two-pass analysis/update/evidence packing, generic operations, and obsolete task owners. Retire their intermediate hard assertions and owning forensic paths in this same cutover. Land deterministic source/dimension retention and live free-text negation-selection/next-context replacements before integration. Adapt the simulation to defaults/preferences and explicit intake finish. R3 only removes residue; it cannot defer these correctness checks.

**Development database handling:** stop every process using the chosen disposable directory, remove only that development database and its WAL/SHM sidecars, and initialize the new schema. Tests use temporary directories. Preserve an untouched private historical export if wanted; add no import/migration compatibility project and never reset the user's normal directory incidentally.

**Required deterministic cases:**

- Fresh initialization is idempotent; no SETUP gate; pre-input preference edits update the snapshot; post-input edits remain pending for future sessions, even after failed generation.
- Sparse intake finishes explicitly; empty intake cannot; no model marks intake complete. User-only intake can produce a provisional plan.
- Self-report dimensions and wording survive exactly; absent/declined/unsure are not denials; changed input metadata conflicts under a reused ID.
- One normal text call; one review plus at most one correction for conversational sessions. Deterministic empty/user-only therapy creates no unsupported strategy and preserves unanswered input/latest useful handoff.
- Complete review source coverage; UTF-8 metadata/many-short-turn limits; exact-fit/overflow boundaries; same-ID retries count source once; oversized fresh input and mandatory sources preserve the draft and fail before acceptance; current text appears once.
- Hidden/foreign/incorrect-role references fail; source chronology comes from IDs; current-session archive selections cannot use historical messages. No removed model-scope field is required.
- Injected failure at each review/reference/plan write leaves no partial artifacts; unchanged plans retain version; required method changes are explicit; completed content is immutable.
- Interrupted/scheduling-failed review can resume/retry; late completion cannot advance a newer attempt or duplicate results; second backend is rejected.
- API/console happy path, source inspection, capacity warning, failure/retry, busy rejection, and uncertain-delivery reconciliation.

Run owning store, application, context, API/OpenAPI, adapter, and console tests, then `make check`. Replace deleted implementation-detail tests while preserving behavioral assertions.

**Live validation:** adapted `make evals`, focused `make eval-report` with human review, and a short two-session real-HTTP journey. R0 establishes design admission; revalidate any prompt/schema/serialization property changed during implementation and verify actual commit/next-context integration. A failed case is not averaged away. Unavailable model-dependent evidence leaves cutover acceptance pending; do not integrate an unproven vertical flow as complete.

**Documentation / exit:** update all six canonical docs, test/eval ownership, root usage, relevant configuration examples, and `AGENTS.md` restatements with implemented behavior. Intake → initial review/plan → therapy → review → next therapy works; no obsolete production owner remains. One schema reset and one supported cutover, with independently reviewable work. Dependency: R1.

## R3 — Delete residual obsolete evidence machinery

**Goal:** keep only hard contracts whose requirements survived R2.

Remove dead extraction/assessment/update forensic helpers, trace joins/digests, duplicate merge replay, stale imports, and report paths after checking their callers. Preserve Phase-10 reports with historical revisions/run references; do not delete private evidence directories. Reduce simulation audit to API results, durable relationships, and a readable failure summary. Add direct test-owned request/result/state capture only where a surviving assertion needs it; use existing gateway/HTTP test seams, not a permanent production observation service.

**Tests:** owning eval/harness and journey tests; missing/duplicate capture, cancellation, raw invalid response, evidence write failure, and simultaneous primary/cleanup failures. A missing promised artifact is a failed claim; actual product failures remain primary. Run `make check`; rerun only live properties affected by capture or oracle changes, respecting their exact-evidence preconditions.

**Documentation / exit:** reconcile test/eval and safety artifact descriptions. No surviving hard test needs trace-v5 replay, no duplicate extraction implementation remains, and R2's source/negation/next-context assertions still hold. Dependency: R2; this step precedes removal of the old event source.

## R4 — Standard logging and explicit sensitive capture

**Goal:** one operational diagnosis path without turning logs into a correctness protocol.

Use stdlib logging, context variables, safe JSON metadata, and rotating handlers. Move logical/physical call logging into the concrete model boundary and remove the diagnostic recorder, wrapper gateway, event sequence/version contract, and command recorder facade. Reuse useful redaction/private-file primitives. Keep a separate opt-in private payload handler with size/incompleteness limits; never enable payloads through ordinary DEBUG. Replace arbitrary exception text with safe codes/frames. Remove automatic shutdown snapshots and provide explicit SQLite-backup export; evals inspect their isolated database.

**Rule:** no operational log consumer becomes a correctness dependency. Product relationships belong in SQLite; hard evidence is captured directly by its owning test. Timing reports may use direct attempt metrics without reconstructing product semantics.

**Tests:** useful metadata with capture disabled; concurrent context isolation; both endpoints' secrets redacted; no patient/provider exception bodies in ordinary DEBUG; private permissions; log/capture failures leave product outcomes unchanged; incomplete capture cannot pass an evidence claim; explicit export consistency; primary/cleanup failures preserved. Run `make check`. A small synthetic capture may be needed for unmocked public raw-response behavior; log formatting alone does not require a therapeutic matrix.

**Documentation / exit:** update architecture, development/configuration, safety, and test/eval ownership. No trace-v5 consumer/source remains; timeout diagnosis works through ordinary logs; database copies are explicit. Dependency: R3.

## R5 — Simplify two-task configuration and structured parsing

**Goal:** remove infrastructure made unnecessary by reducing six tasks to conversation/review.

Keep `pydantic-settings`, `.env`, and one loader with environment-over-dotenv-over-default precedence. Reduce resolved configuration to `EndpointProfile` and `CallPolicy`; remove obsolete task overrides, independent nullable-field inheritance, and redundant parsing. Default both responsibilities to the same profile; a distinct endpoint has explicit identity/credentials. No TOML, secret-name indirection, new registry, or second configuration language.

Implement the structured-mode decision frozen in R0. Target `json_schema` only; retain any additional mode solely for its documented required endpoint. Admit the then-locked SDK's public Pydantic parsing with exact-request, invalid-result, finish/refusal, and opt-in raw-capture tests. Delete Jung's schema transform/second walk if admission passes. Otherwise keep a narrow direct-create implementation of the same admitted mode, documenting the measured SDK limitation. Semantic validation and one correction remain Jung-owned; no private SDK imports or hidden retries.

**Tests:** settings precedence/invalid keys, default profile sharing, explicit second endpoint/credentials, exact physical attempt counts, serialized schema/options, failure mapping, correction deadline, and raw capture on parse failure; `make check`. Run `make smoke-local-llm` and relevant `make evals` for changed adapter/structured behavior. Reuse R0/R2 evidence only for properties the new parsing/configuration cannot invalidate.

**Documentation / exit:** update configuration examples and canonical supported-endpoint/mode claims to the admitted target. Only two task policies and required structured paths remain. Dependency: R4; broad configuration and parsing redesign happens after therapeutic deletion.

## R6 — Validate historical selection at 100-session scale

**Goal:** useful continuity and inspection with bounded reads, before adding retrieval machinery.

Use dedicated latest-handoff, recent-exchange, recent-reference, and source-read queries instead of loading all reviews. Retain mandatory handoff anchors, bounded explicit recall, and preceding unanswered patient input; fill optional history from recent `memory_refs` with the ordering in [data and context](04-data-and-context-model.md). Fetch dated full messages and deduplicate by ID. Complete console source navigation and ordinary cursor/limit pagination. Log omission counts/reasons without persisting prompt snapshots. Measure SQL/serialization cost on 100 synthetic sessions; add ordinary indexes only when query plans warrant them.

**Tests:** old anchors/explicit recall versus irrelevant recent messages, recent candidate ordering, same-wording distinct IDs, conflicting dated reports, multilingual sources, oversized mandatory input, no-content handoff continuity, pagination/source lookup. Record unanchored recall misses honestly; do not pretend recency performs semantic search. Run `make check`; run focused handoff/negation replays only when selection changes invalidate prior evidence. A 100-session live journey is unnecessary to measure bounded SQL work.

**Optional R6b:** only a demonstrated material miss on the fixed recall cases justifies a separate lexical-matching change. Compare the same cases before/after; use bounded terms and parameterized SQL, no retriever framework. FTS needs further demonstrated need; embeddings remain deferred. No lexical implementation is owed if the baseline suffices.

**Documentation / exit:** describe actual recall limits and explicit source inspection in architecture/API/test/eval docs. Active request construction is bounded, required sources survive, and known unanchored misses are recorded with any justified follow-up. No new schema reset is expected. Dependency: R5.

## R7 — Consolidate, retire, and accept

**Goal:** leave one understandable architecture and a small maintained verification surface.

Retire closed experiment executables such as `phase8d/patient_benchmark.py`, retaining outcome documents and original revision/run references. Keep reusable synthetic scenarios and a selectable behavioral report without default matrix expansion. Simplify Make targets around deterministic checks, configured-model admission, selected hard/qualitative cases, and one journey command. Remove dead imports/configuration/tests that freeze deleted layouts; preserve concurrency, HTTP, SQL, provenance, and trust-boundary coverage. Reconcile canonical docs and `AGENTS.md`, then mark this plan implemented or superseded with revision links.

Read the flow from API → application → context/prompt → model → store as a new developer. If it needs a new registry, event model, or hidden fallback to explain, simplify it. No feature is removed merely because its file is long.

**Validation / exit:** `make check`, focused tests for changed behavior, documentation links including this directory, and import-boundary/public-SDK checks. Reuse applicable R0/R2/R6 evidence; rerun the short journey only when integration changes invalidate it. Do not require a ceremonial long run. Acceptance below must be complete, actual maintenance reduction documented, and live-validation gaps explicit; pending required evidence prevents claiming completion. Dependency: R6 and any required R6b.

## Simplification ledger

These are responsibility budgets, not invented line-count forecasts. At each integration, record the actual production/eval diff and explain growth; do not manufacture deletions or sum overlapping inventories. The earlier M0–M6 estimates are superseded by this sequence.

| Step | Added or retained responsibility | Deleted or deliberately deferred responsibility | Dependency change |
|---|---|---|---|
| R0 | Eval-only compact schema, fixed fixtures, admission evidence | No production restructuring before proof | None |
| R1 | Finite attempts/output/deadlines, explicit failure and credentials | Unlimited/truncated success; defer broad settings/evidence rewrites | None |
| R2 | Unified review, session work, explicit finish/input metadata, fixed source bound | Extraction/completeness, ranked assessment, second review call, operations, SETUP, owning obsolete forensics | No new runtime dependency |
| R3 | Small direct evidence for surviving hard claims | Residual trace reconstruction, merge replay, intermediate matrices | None |
| R4 | Safe logs, opt-in payload capture, explicit export | Recorder lifecycle/schema, wrapper gateway, automatic snapshots | Stdlib; reuse redaction |
| R5 | EndpointProfile and CallPolicy; admitted public SDK parsing | Six-task settings, unneeded structured modes/schema walks; no TOML | Existing SDK/Pydantic/settings |
| R6 | Bounded recent queries and explicit source inspection | Whole-history loading; lexical/FTS/embeddings deferred until measured need | None |
| R7 | Historical reports and reusable cases | Closed executable experiments and dead supported paths | No required runtime addition |

The expected outcome remains a several-thousand-line production reduction and a substantial eval reduction, not a promised percentage. HTTP, SQL integrity, and cancellation code intentionally remain. Fixed capacity, source input metadata, and session recovery earn their cost; persistent capacity profiles, compatibility adapters, duplicate plan/handoff ownership, and unconsumed review fields do not. Seven useful dependencies may remain seven.

## Target acceptance checklist

- [ ] R0 admits a useful compact review on every frozen case within one correction, with human comparison and explicit endpoint/mode/envelope decisions.
- [ ] Warning-free baseline established separately; one backend owns each directory; deterministic tests use isolated data and no live model.
- [ ] A new developer can identify conversation, review, source truth, current strategy, and next context without historical phase knowledge.
- [ ] Intake starts with visible editable defaults, freezes preferences at first accepted input, and can finish with uncertainty to create one provisional plan.
- [ ] One normal text call and one bounded review plus at most one correction; physical attempts, terminal handling, and total deadlines tested.
- [ ] Patient text, explicit self-reports, historical wording, and generated interpretation have distinguishable owners; later corrections preserve earlier history.
- [ ] Review sees the full session within one fixed product envelope; mandatory sources fit; warning/rejection preserves drafts; any retry endpoint fits the same envelope.
- [ ] Failed/cancelled/retried work cannot create partial plans, duplicate relationships, or false stream completion; recovery has one owner and attempt fencing.
- [ ] Ordinary logs exclude payloads and are never correctness dependencies; exact capture/export is explicit and private.
- [ ] Source/negation/instruction cases, qualitative review, and an applicable short journey support continuity; 100-session tests cover anchors/explicit recall and record unanchored limits.
- [ ] No old task modes, operation result owners, duplicate plan recommendations, forensic event dependencies, or speculative configuration/retrieval systems remain.

## Deliberate final simplification pass

| Question | Decision |
|---|---|
| Can a component disappear? | Delete extraction, assessment, retrospective update, operations, and SETUP when their surviving requirements have direct owners |
| Can two concepts become one? | Intake/therapy share conversation; initial/later analysis share review; work identity is the source session |
| Is information duplicated? | Plans own strategy, messages own wording, memory rows own selections; no durable capacity projection or second plan copy |
| Is derived material pretending to be truth? | Review/plan content remains interpretation; citations expose sources without proving entailment |
| Can logs replace forensic machinery? | Yes for diagnosis; never as a correctness dependency; direct evidence belongs to the test |
| Can one call replace two? | Freeze only after R0; refine schema or revise the decision before production restructuring |
| Is the review schema overloaded? | Remove unconsumed fields and model-authored scope; retain only independently useful sections |
| Is another format/framework needed? | Keep existing SQL, asyncio, HTTP, SDK, Pydantic, and dotenv; no TOML or job/retriever framework |
| Does history growth require lexical retrieval? | First measure anchors, explicit recall, and recent selections at 100 sessions; add retrieval only for demonstrated misses |
| Is another live run needed? | Only for a changed property or unmet named gate; historical evidence remains historical |
| Is the one-laptop constraint exploited? | One process lock and owned task; no distributed jobs, provider router, or inference orchestrator |

## Planning deliverable validation

### Original plan — 2026-09-06

This section records checks of the **documents**, not validation of the future runtime. Production and local model configuration were not modified; no database reset or live model evaluation was performed for this planning task.

`make docs-links` passed. `make check` passed: format/lint/documentation checks, **1,037 unit/integration tests**, and **3 console tests**. The unchanged suite emitted one warning that a `run_local` coroutine was never awaited; that warning is recorded rather than repaired in this documentation-only task.

The additional plan-specific check also **passed** using `md-link-checker==1.10 --no-urls architecture-plan/*.md`, after replacing four section-link forms that this checker treated as file paths. Local source links and Markdown code-fence balance were also inspected; `git diff --check` passed. No new runtime tests were added for documents. Model latency/quality improvements remain hypotheses until the migration's named experiments are executed.

### Feedback revision — 2026-09-20

Revised six planning documents on top of `632cdcb`; retained the dated current-state inspection and original validation record. No production code, canonical runtime docs, model settings, or product database changed. The dedicated branch move and coroutine-warning fix remain future migration preparation, not actions performed in this documentation task.

`make docs-links`, the additional `md-link-checker==1.10 --no-urls architecture-plan/*.md` check, and `git diff --check` passed. Fresh `make check` passed format/lint/documentation checks, **1,037 unit/integration tests**, and **3 console tests**. The existing `run_local` coroutine warning recurred once; R0 explicitly requires its separate correction before declaring a warning-free migration baseline. The checks required access to uv's cache outside the workspace after sandboxed attempts were blocked.

Reviewed decision/phase cross-references, preference-freezing semantics, derived source chronology, mandatory-source capacity, and examples against the revised target. No live model evaluation was run: R0 one-call/schema/endpoint/envelope admission remains pending, and this document validation does not establish it.
