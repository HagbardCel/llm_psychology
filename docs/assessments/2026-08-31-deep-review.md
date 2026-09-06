# Deep Architecture Review — Edition 3

> Assessment date: 2026-08-31. Scope: the `jung` repository as of commit
> `18d18898` on branch `fix/phase-10-intake-completion` (9 days and ~30 commits
> after the v2 base `c62b7c2`). This is a point-in-time advisory document. It
> does not change any contract in the canonical documentation
> ([Architecture](../architecture.md), [Workflow](../workflow.md),
> [Database](../database.md), [API v1](../api-v1.md)); where it discusses
> changing behavior, the change becomes real only when implemented, tested, and
> synced into the owning canonical document.
>
> This edition **does not supersede** [Edition 2](2026-08-22-codebase-leanness-assessment-v2.md).
> Edition 2 remains the authoritative consolidation inventory. This edition adds
> the one track v2 deliberately excluded — **feature/scope decisions for a
> single-user local therapist at this stage** — prompted by the operator's
> explicit willingness to remove low-priority features and to consider
> fundamental refactors. v2's findings (F1–F17) are re-verified below; none were
> addressed in the interim, so the v2 budget is still on the table.

## 1. Purpose and method

The product goal is a functional, lean, maintainable local AI therapist for one
user on one laptop, supporting multiple therapy styles and detailed logging to
identify issues at this stage. This review:

1. re-verifies v2's consolidation findings line-by-line against current source;
2. identifies simplification *within* the supervisor/post-session pipeline that
   v2 did not pursue (the pipeline is confirmed as a keeper, §3);
3. lays out scope/feature decisions the operator must make — chiefly the
   evals/simulation surface — with per-surface cost/benefit;
4. re-evaluates third-party library adoption "more intensively" under the
   locked constraints, and reports an honest verdict;
5. lists what must not change, and gives a prioritized, validation-aware plan.

Method: full read of every production module over ~400 LOC, the schema, the
canonical docs, the test/eval READMEs, the Makefile, and the prior assessments;
line-level re-verification of each v2 finding cited below.

### 1.1 What changed since v2

The 9-day window delivered Phase 9–10 intake work and eval hardening, not
consolidation:

- `feat(intake): separate extraction contract from durable evidence` /
  `integrate extraction-owned intake_patch contract` (PR #75) — the
  `intake_patch` task now uses an extraction-only `IntakeExtraction` schema;
  Jung materializes durable `IntakeEvidence` provenance after validation
  (`architecture.md:284–287`). The intake phase is now **larger and more
  complex than v2 measured** (~922 LOC across `intake/*`; see §5.4).
- `feat(diagnostics): record intake turn decisions` — new
  `intake.turn.evaluated` diagnostic events in `_application/chat.py:437–463`.
- `feat(simulation): project intake forensics into audit.md` and the Category C
  evidence/forensics hardening series — the evals/simulation tree **grew**, not
  shrank (see §6.3).

None of v2's F1–F17 consolidation targets were touched. The two findings I
spot-checked most carefully are unchanged: the `UtcDateTime` duplication is
still byte-identical (`domain/models.py:26` and `api/contracts.py:23`), and the
two provider error ladders in `openai_compatible.py` are still there
(`stream_text` `:372–464`, `_make_provider_request` `:777–809`).

## 2. Project profile (current)

| Area | Python LOC | Change vs v2 | Notes |
|---|---:|---|---|
| `src/jung` production | 14,486 | +417 | intake extraction ownership + diagnostics |
| `tests/` | 32,675 | +3,517 | Phase 9–10 regressions, intake smoke path |
| `evals/` | 9,927 | +2,903 | simulation forensics, Category C evidence |

Test:production ratio ≈ 2.25:1 (deterministic suite ≈ 1.8:1). Largest production
modules are unchanged in rank: `persistence/sqlite_store.py` 1,237 (8.5%) ·
`llm/openai_compatible.py` 849 (5.9%) · `client/api_client.py` 693 (4.8%) ·
`_application/chat.py` 626 (4.3%) · `application.py` 590 (4.1%) ·
`client/console.py` 560 (3.9%) · `diagnostics.py` 538 (3.7%).

Package distribution: `phases/` 3,934 · `llm/` 1,767 · `api/` 1,585 ·
`persistence/` 1,519 · `client/` 1,421 · `_application/` 1,346 · `domain/` 597
· top-level 2,248.

Seven runtime dependencies, unchanged: `openai`, `pydantic`,
`pydantic-settings`, `fastapi`, `uvicorn`, `httpx`, `prompt-toolkit`. Dev:
`ruff`, `pytest`, `pytest-asyncio`. Hygiene clean; zero TODO/FIXME in `src/jung`.

**Verdict up front (revised):** v2's claim that the codebase is "already
unusually lean for its feature set" still holds. But this edition asks a
different question v2 avoided: *which features and subsystems earn their
maintenance cost for a single-user local therapist at this stage?* With the two
largest structural cuts (supervisor pipeline, HTTP boundary) confirmed
off-limits by the operator (§3), the honest answer is that no large structural
win remains available — the realistic maintenance reduction is **≈555–750 LOC
of v2 consolidation + ≈150–250 LOC of optional client-strictness relaxation +
≈3–4k LOC of evals/simulation trimming if the operator accepts it**. The
operator's "remove low-priority features" lever applies most forcefully to the
evals/simulation tree, not the product core.

## 3. Constraints locked by the operator

Two product-direction decisions were confirmed up front and bound this review:

1. **The supervisor + post-session + assessment + grounding + plan-revision
   pipeline is a core feature.** It is kept. This removes the single biggest
   LOC-reduction lever (dropping ~3–4k LOC of supervisor machinery) from
   consideration. §5 therefore proposes *simplification within* the pipeline,
   not removal.
2. **The HTTP API boundary is kept.** A future local browser frontend is very
   likely. This removes the in-process-console lever (dropping ~2.3k LOC of
   `api/` + `client/api_client.py`) from consideration. §6.1 notes the one
   consequence worth acting on: the terminal console becomes a secondary
   client, which weakens the case for its full defensive strictness.

Everything below is scoped accordingly.

## 4. Tier 1 — endorse v2 consolidation (≈555–750 LOC, no behavior change)

Every v2 finding was re-verified against current source. All are still
actionable; none were addressed in the interim. The estimates and evidence
below are v2's, re-confirmed; see Edition 2 for full detail. Ordered by
value-to-effort.

| # | Finding | Evidence (re-verified) | Est. |
|---|---|---|---:|
| F1 | Adapter error-ladder dedup | `openai_compatible.py` two near-identical try/except ladders (`:372–464`, `:777–809`); five + six except blocks repeating set-status/record/re-raise | −80–120 |
| F8 | Command-frame context manager | `application.py:262–524` repeats an identical ~25-line frame across `update_profile`/`select_style`/`start_session`/`end_session`/`retry_operation` | −80–100 |
| F13 | API mechanical layer | `mapping.py` field-copy converters; `errors.py:88–114` three dead specs duplicating the default; `app.py` lifespan; `routes.py` 9× `Depends` repetition | −110–150 |
| F9 | `tracing.py` consolidation | `ObservedLLMGateway` duplicates outcome blocks `stream_text:97–163` vs `generate_structured:221–274`; dead `finally: pass` at `:182–183` | −60–80 |
| F11 | Chat context blocks + terminalize | `_application/chat.py` 8× `diagnostic_context(...)` blocks; `_terminalize_ordinary_drained:507–546` vs `_terminalize_final_intake_drained:548–606` share most of their body | −50–70 |
| F2 | Unified shield-and-drain helper | three identical-shape sites: `store_calls.py:30–49`, `chat.py:374–383`, `chat.py:610–622`; latter two differ only in sentinel class | −25–40 |
| F3 | Fuse JSON validation into serialization | `persistence/_sqlite_support.py:118–185` pre-validates before `json_dumps` (which already uses `allow_nan=False`); only non-string-key check must survive | −50–60 |
| F10 | Strict-schema assert → test-owned | `llm/structured.py` walks JSON-schema payload twice; `assert_valid_strict_provider_schema` only called right after the transform it re-checks | −43 |
| F4 | Shared `UtcDateTime` | `_as_utc`+`UtcDateTime` defined identically at `domain/models.py:22–26` and `api/contracts.py:19–23` (confirmed) | −8 |
| F5 | Named-access row codecs | `_sqlite_support.py:202–279` all positional `row[0]…row[12]`; a column reorder silently corrupts models. Neutral LOC, kills a bug class | +15 |
| F12 | Operations symmetry + ownership field | `_application/operations.py:212–238` vs `:239–289` parallel completion bookkeeping; `_operation_task`+`_operation_task_id` double-tracked (`:147–148`, `:66–71`) | −25–40 |
| F16 | Diagnostics write-path dedup | `diagnostics.py:430–451` vs `:459–476` two parallel sanitize-then-write paths | −15–20 |
| F17 | Composition fallback resolver | `composition.py:191–209` repeats `supervisor_value if set else session_value` ×5 | −10–15 |
| µ | Micro-trims | `console.py` retry-prompt loops `:250–280`/`:362–378`; `local.py:16–18` opens a throwaway client just for a health probe | −20–25 |

**Tier-1 subtotal: ≈555–750 LOC net**, zero intended behavior change. Every
item maps to an AGENTS.md validation-matrix row (see §8). None require schema,
API-contract, or dependency changes.

v2 also lists two Tier-B (semantic-surface) consolidations that this edition
keeps endorsing, now under the §5 lens: F14 (three context-packing
orchestrators) and F15 (merge mechanics). They are restated with sharpened
feasibility below because the kept-supervisor constraint makes them the most
valuable *in-pipeline* reductions available.

## 5. Tier 2 — simplification within the kept supervisor pipeline (NEW)

v2 treated the supervisor pipeline as out of scope for consolidation. With the
pipeline confirmed kept, these reductions become the highest-value work after
Tier 1, because they cut code that must be maintained for the lifetime of the
feature.

### 5.1 Flatten `OperationRuntime` for a single-user model

**Evidence:** `_application/operations.py` (348 LOC) implements a full task
ownership protocol: `schedule`, `schedule_retry` (with a `add_done_callback`
re-schedule dance, `:150–160`), `_operation_task` + `_operation_task_id`
double-tracking (`:55–56`, `:147–148`, `:66–71`), a
`_record_scheduling_invariant` path for "cannot schedule a second operation"
(`:106–121`), and a `shutdown` that shields and drains the owned task
(`:73–90`).

**Why it's heavier than the scenario needs:** the architecture guarantees *at
most one* pending/running/failed operation globally
(`schema.sql:107–109`, `database.md:67`), and the product is single-user,
single-process. The "two operations scheduled at once" invariant can only fire
under a bug, not a real workload. The retry path (`schedule_retry`) exists for
`FAILED` operations that the operator can already retry via the explicit
`/operations/current/retry` command (`routes.py:280–293`) — the auto-reschedule
on a live task is a second path to the same end.

**Recommendation:** a flat `run(operation_id)` that acquires the mutation lock,
marks `RUNNING`, runs the worker, and on exception marks `FAILED` — without the
double-tracked ownership fields, the re-schedule callback, or the
scheduling-invariant branch. Keep `shutdown`'s shield-and-drain (it serves the
bounded-shutdown contract). The explicit `retry_operation` command path already
covers retry; startup recovery (`application.py:140–169`) re-schedules
`PENDING`. Estimated **−50–100 LOC** plus one fewer parallel invariant to
maintain. v2 F12 (symmetry + ownership field) is a subset of this; do them
together.

**Validation:** `tests/integration/application/test_application_operations.py`,
recovery tests in `test_application_recovery.py`; `make check`.

### 5.2 Post-session two-call chain: keep the split, fold the bookkeeping

**Evidence:** `post_session/processor.py:115–145` runs two structured calls —
`analysis` (sequence-cited `SessionAnalysis`) then `update` (resolved-patient
`PostSessionUpdateResult`). The split is **deliberate and load-bearing**, not
redundant: the analysis cites *sequences only* and never sees resolved patient
text (`workflow.md:204–211`); the update prompt receives the backend-resolved
full turns and produces the briefing + plan patch. Merging them into one call
would either leak resolved patient text into the analysis schema (violating
the evidence-layer model) or lose the briefing/plan-patch output. **Keep the
split.**

**Recommendation:** the reducible part is the surrounding bookkeeping:
`_minimal_session_result` (`:38–78`) and `_compose_result` (`:81–100`) plus
the `validate_result` lambdas can share a small assembly helper. Minor
(~15–25 LOC) and behavior-preserving.

**Validation:** `tests/unit/phases/post_session/test_post_session_processor.py`;
`make eval-report` when configured (prompt-affecting adjacency).

### 5.3 Three context-packing orchestrators (v2 F14, restated)

**Evidence (current):** `context_projection.py` (459 LOC) is a genuinely lean
shared primitives layer — `_compact_string_list:80`, `minimal_plan_projection:96`,
`enrich_plan_projection:158`, `enrich_session_briefing_projection:244`,
`pack_prior_session_reviews:302`, `pack_transcript_turns:350`,
`pack_grounded_patient_messages:422`, all parameterized by caller-owned `fits`
predicates. The duplication is one level up, in three builders that re-implement
the same priority sequence (minimal plan → pack transcript/evidence → enrich
plan → briefing minimal-then-enrich → grounded messages → prior reviews) with
local `*_fits` closures:

- `therapy/context.py` (`build_untrusted_therapy_document`)
- `post_session/analysis_context.py:48–190` (`build_analysis_document`)
- `post_session/update_context.py:260–409` (`build_update_user_message`)

**Feasibility call (sharpened):** this remains the **highest-risk** reduction in
the report. `update_context.py` carries phase-specific invariants — frozen
evidence keys (`:36–44`) and evidence packed *before* interpretive enrichment
(`:266–272`) — that resist a uniform recipe. A wrong abstraction silently
changes prompt content, which is product semantics, not plumbing.

**Recommendation:** a *modest* declarative "packing recipe" (ordered list of
`(key, producer, optional)` steps sharing one document+fits loop) is worth
attempting **only after** the owning context tests are green and with a
`make eval-report` diff in hand. Do not attempt a uniform framework. If the
first attempt forces `update_context.py`-specific escape hatches, abandon and
leave the three builders as-is — the current shape is correct, just verbose.
Estimated **−150–250 LOC** *if* it lands cleanly.

**Validation:** `tests/unit/phases/test_context_projection.py`,
`tests/unit/phases/therapy/test_context.py`,
`tests/unit/phases/post_session/test_update_context.py` +
`test_post_session_prompts.py`; `make eval-report` when configured.

### 5.4 Merge mechanics (v2 F15, restated) — and an intake-complexity flag

**Evidence:** `post_session/merge.py:21–41` `apply_plan_patch` is fully
mechanical field-by-field (`patch.x if patch.x is not None else current.x` ×6);
`PlanContent.model_copy(update=patch.model_dump(exclude_none=True))` collapses
it to ~8 LOC. Low risk. `intake/merge.py` (415 LOC) is split: the drop rules
are semantic and load-bearing (source-role/sequence checks, strict
quote-in-message validation, confidence-rank conflict resolution, list dedup) —
keep; but `_merge_validated_patch` restates the `IntakeRecord` schema
field-by-field and must be edited whenever the model changes.

**Recommendation:** collapse `apply_plan_patch` outright (low risk); convert
`_merge_validated_patch` to a declarative `(path → merge strategy + cap)` spec
walked generically (moderate; drop-reason diagnostics must survive verbatim).

**Intake-complexity flag (NEW):** Phase 9–10 made intake the most complex phase.
The intake subsystem is now ~922 LOC (`merge.py` 415 + `extraction.py` 316 +
`models.py` 237 + `processor.py` 154 + `completion.py` 191 + `prompts.py` 160
= 1,473 LOC if you count `models`+`prompts`; ~922 for the logic core). The
extraction-ownership refactor added a real contract (`IntakeExtraction` schema
separate from durable `IntakeEvidence`), which is correct, but it also added
the materialization + merge-diagnostics surface that `chat.py:437–463` now
records per-turn. This is the subsystem most worth a future dedicated
simplification pass — not because it is wrong, but because it concentrates the
highest cognitive load per line. Record as a watch item, not an action this
cycle.

**Validation:** `tests/unit/phases/intake/test_merge.py`,
`tests/unit/phases/post_session/test_post_session_merge.py`; `make eval-report`
when configured for prompt-affecting adjacency.

## 6. Tier 3 — scope decisions laid out for the operator (NEW)

With the supervisor and HTTP boundary locked, the remaining scope levers are
smaller and outside the product core.

### 6.1 Terminal-console strictness (v2 F7, re-examined)

**Evidence:** `client/api_client.py` (693 LOC) spends roughly 300 LOC on
defensive protocol machinery: a 12-member `ProtocolErrorKind` taxonomy,
sanitized nested-validation reporting, request-ID echo verification, an
error-code↔HTTP-status cross-check table, media-type checks, and stream-event
correlation checks. v2 F7 said "keep as is" because it converts silent contract
drift into loud fail-fast errors.

**What changed:** the operator confirmed a future local browser frontend is
likely. The browser will talk to `/api/v1` directly over HTTP; the Python
`api_client` serves *only* the terminal console. As the terminal console
becomes a secondary client, the case for full fail-fast strictness in the Python
client weakens — it monitors a loopback contract between two components that
ship together and are already covered by `tests/integration/client/` and the
`e2e` probe.

**Recommendation (relax, not remove):** keep the typed `JungApiClient` surface
and the `FakeLLM`-style test faithfulness, but demote ~150–250 LOC of
cross-checks (request-ID echo, status↔code cross-table, media-type asserts)
from raising `ProtocolError` to `logger.warning`. This preserves observability
for the "identify issues at this stage" goal while reducing the surface that
can turn a benign console/server version skew into a hard failure. Revisit if
the terminal console is ever promoted back to the primary client.

**Validation:** `tests/integration/client/` + `tests/e2e/test_console_workflow.py`;
`make check`.

### 6.2 Third-party libraries — re-evaluated "more intensively"

The operator asked to evaluate library adoption more intensively. Re-run against
the AGENTS.md dependency policy (*add a dependency only when it removes a
meaningful Jung-owned responsibility; which Jung code disappears?*) **under the
locked constraints** (supervisor kept ⇒ structured-output loop stays
Jung-owned; HTTP kept ⇒ FastAPI stays):

| Candidate | Would replace | Verdict under locked constraints |
|---|---|---|
| SQLAlchemy / SQLModel | `SQLiteStore` SQL + codecs | **No.** The store's explicitness *is* the design; an ORM deletes little of the 1,519 LOC, most of which is workflow-coupled mutation logic. Forbidden by architecture. |
| pydantic-ai / Instructor / Outlines | structured-output loop | **No.** The supervisor is kept, so the single-correction + `max_retries=0` physical-attempt contract stays product-owned. v2 Appendix A's full pydantic-ai evaluation holds unchanged. |
| structlog / OpenTelemetry | diagnostics/logging | **No.** `diagnostics.py` owns deterministic pre-disk redaction, 0600 file modes, fail-latched writes, and SQLite backup-API snapshots (`:148–314`) — product safety requirements no library provides. OTel is disproportionate for a local-first tool. |
| Tenacity | retry logic | **No.** Retries are intentionally absent (fail-fast rule). Verified: the client has no retry/backoff; resilience is one transport timeout + caller-side re-sync. |
| Textual / Rich | console rendering | **No.** Rendering is delegated to a `ConsoleOutput` protocol; input goes through `prompt_toolkit`. No rendering machinery exists to offload. |
| Typer / Click | three small CLIs | **No.** argparse usage is ~60 lines across entry points. |
| anyio / Trio | asyncio runtime | **No.** Forbidden (one asyncio runtime). |
| httpx-sse / sse-starlette | NDJSON streaming | **No.** Transport is NDJSON, not SSE; the hand-rolled parser is ~55 LOC. |
| openapi-python-client / datamodel-code-generator | typed client | **No for the Python client** (it already imports all wire types from the shared `jung.api.contracts` — zero duplicated DTOs, `api_client.py:22–41`). **Yes for the future browser client** — a TS/JS client generated from the OpenAPI schema (`/api/v1` is FastAPI, so `/openapi.json` exists) is reasonable and adds zero backend deps. |

**Conclusion:** no new backend runtime dependencies are warranted. v2's
seven-dependency stack is still right-sized for the backend. The single
library-direction shift this edition endorses is **OpenAPI codegen for the
future *browser* client**, which is a frontend concern and does not touch the
backend dependency list. The honest reading: under the locked constraints,
libraries do not help — the remaining bulk is product logic and deliberate
strictness, exactly as v2 found.

### 6.3 Evals surface trade-off (operator undecided)

The evals + simulation tree is ~9,927 LOC. Only `make evals` (hard safety
invariants) is a gate; the behavioral report and simulation are research
instruments. Per-surface cost/benefit:

| Surface | LOC | Purpose | Gate? | Recommendation |
|---|---:|---|---|---|
| Hard invariants | ~2,400 (`test_hard_invariants.py`, `test_intake_clear_risk_denial.py`, `intake_risk_denial_evidence.py` 852, `harness.py` 518, `scenarios.py` 892, `execution.py`) | Contractual model safety: canary non-disclosure, injection resistance, citation integrity, negation selection, Category C denial retention | **Yes** (`make evals`) | **Keep.** This is the gate the product depends on. |
| Behavioral report | ~975 (`behavioral_report.py`) + shared scenarios | Diagnostic matrix (safety×style, style differentiation, assessment quality) for human review | No | **Keep**, but the report is the highest-value-per-LOC eval surface; do not cut. |
| Simulation + forensics | ~5,300 (`simulation/runner.py` 1,240, `simulation/audit.py` 2,212, `intake_forensics.py` 1,370, `phase8d/patient_benchmark.py` 485, `simulation/scenarios.py`, `simulation/patient.py`) | Whole-product longitudinal journey audit over real HTTP | No | **Trim.** This is the single largest eval surface and the strongest candidate for the operator's "remove low-priority features" lever. The mechanical audit gates (persistence, plan lineage, grounding, briefing→next-prompt) are valuable; the forensics/benchmark scaffolds around them are not. Recommend extracting the ~600–900 LOC of mechanical audit checks into a lean `simulate-and-audit` and **dropping the forensics/benchmark scaffolds** unless they are actively informing current work. Cut: **~3–4k LOC**. |
| Archived phase experiments | `evals/phase8b/`, `evals/phase8c/`, `evals/phase8d/` | Closed experiments with recorded OUTCOMEs | No | **Archive/remove** the scripts. Their OUTCOME.md files should stay for provenance, but the carrying scripts (e.g. `logs/evals/phase8b/vendor-llguidance/...`, the parallel-journey orchestration removed in `52b97c8`) are dead weight. |

**If the operator accepts:** the evals tree drops from ~9,927 to ~4,500–5,500
LOC, retaining every gate and the diagnostic report, while removing research
scaffolding that is no longer earning its maintenance cost.

**Validation note:** evals are opt-in and do not run in `make check`, so cutting
them is low-risk to the deterministic gate. But `tests/unit/evals/` and
`tests/integration/evals/` (which *do* run in `make check`) pin the simulation
harness mechanics; any trim must keep those tests' targets or move them.

## 7. What must not change

- Message-native chat truth and request-owned streaming semantics
  (`workflow.md:96–146`).
- Store-owned transaction boundaries and DDL-enforced invariants (schema v7,
  `database.md:50–69`).
- Structured-output ownership, single-correction semantics, `max_retries=0`
  (`openai_compatible.py:152`, `:540–620`).
- Diagnostic capture being strictly best-effort and side-effect-free
  (`diagnostics.py`, `safety-and-data.md`).
- Fixed two-role LLM routing defined in source (`architecture.md:239–267`).
- The no-migration, reset-the-database stance (`architecture.md:62–63`).
- The wire/domain DTO split (architecturally forced; only the mechanical mapper
  *bodies* are reducible, per F13).
- The supervisor/post-session evidence-layer model: analysis cites sequences
  only; the backend resolves patient turns for the update prompt only
  (`workflow.md:204–246`). §5.2 keeps this; any "one-call" merge of analysis +
  update would violate it.

## 8. Prioritized action plan

Three columns reflect the three tracks. Each row carries file:line evidence,
estimated net LOC, and the AGENTS.md validation-matrix row.

### Track A — v2 consolidation (no behavior change; do first)

| # | Action | Evidence | Est. LOC | Validation |
|---|---|---|---:|---|
| A1 | F5 named-access row codecs | `_sqlite_support.py:202–279` | +15, kills a bug class | focused store tests + `make check` |
| A2 | F8 command-frame context manager | `application.py:262–524` | −80–100 | `tests/integration/application/` + `make check` |
| A3 | F1 adapter error-ladder dedup | `openai_compatible.py:372–464`, `:777–809` | −80–120 | `tests/unit/llm/` + `make check`; `make smoke-local-llm` when available |
| A4 | F3 fuse JSON validation into serialization | `_sqlite_support.py:118–185` | −50–60 | focused store tests + `make check` |
| A5 | F2 unified shield-and-drain helper | `store_calls.py:30–49`, `chat.py:374–383`, `chat.py:610–622` | −25–40 | cancellation tests + `make check` |
| A6 | F13 API mechanical layer | `mapping.py`, `errors.py:88–129`, `app.py`, `routes.py` | −110–150 | `tests/unit/api/` + `tests/integration/api/` + `make check` |
| A7 | F9 tracing consolidation | `tracing.py:97–163`, `:182–183`, `:221–274` | −60–80 | `tests/unit/llm/test_tracing.py` + `make check` |
| A8 | F10 strict-schema assert → test-owned | `llm/structured.py:186–228`, `:235–237` | −43 | `tests/unit/llm/test_structured_output.py` + `make check` |
| A9 | F11 chat context helper + terminalize merge | `chat.py:142–146`…`:539–543`, `:507–606` | −50–70 | chat/cancellation tests + `make check` |
| A10 | F4 shared `UtcDateTime` | `domain/models.py:22–26`, `api/contracts.py:19–23` | −8 | `make check` |
| A11 | F12 operations symmetry + ownership field | `operations.py:212–289`, `:55–71`, `:147–148` | −25–40 | operations/recovery tests + `make check` |
| A12 | F16 diagnostics write path; F17 composition resolver; micro-trims | `diagnostics.py:430–476`; `composition.py:191–209`; `console.py:250–280`; `local.py:16–18` | −45–60 | owning tests + `make check` |

**Track A subtotal: ≈555–750 LOC net.**

### Track B — in-pipeline simplification (kept supervisor)

| # | Action | Evidence | Est. LOC | Validation |
|---|---|---|---:|---|
| B1 | Flatten `OperationRuntime` (subsumes F12) | `_application/operations.py:55–160` | −50–100 | operations/recovery tests + `make check` |
| B2 | Fold post-session assembly bookkeeping | `post_session/processor.py:38–100` | −15–25 | `test_post_session_processor.py` + `make check`; `make eval-report` if configured |
| B3 | Context-packing recipe (v2 F14) — only if it lands cleanly | `therapy/context.py`, `post_session/analysis_context.py:48–190`, `post_session/update_context.py:260–409` | −150–250 | context tests + `make eval-report` |
| B4 | Merge mechanics (v2 F15) | `post_session/merge.py:21–41` (low risk), `intake/merge.py:_merge_validated_patch` (moderate) | −85–105 | merge tests + `make eval-report` |

**Track B subtotal: ≈300–480 LOC**, touching semantic surfaces — follow the
AGENTS.md semantic-behavior row.

### Track C — scope decisions requiring operator sign-off

| # | Action | Evidence | Est. LOC | Validation |
|---|---|---|---:|---|
| C1 | Relax terminal-console client strictness to logging-only | `client/api_client.py` (~300 LOC of cross-checks) | −150–250 | `tests/integration/client/` + `e2e` + `make check` |
| C2 | Trim simulation + forensics to a lean mechanical audit | `evals/simulation/` ~5,300 LOC core | −3,000–4,000 | `tests/unit/evals/` + `tests/integration/evals/` (keep targets) + `make check`; live `make simulate-local-llm` optional |
| C3 | Archive/remove closed phase-experiment scripts | `evals/phase8b/`, `phase8c/`, `phase8d/` scripts | −variable | `make check` (ensure no test imports them) |

### Track D — documentation (no behavior)

| # | Action | Evidence | Est. LOC | Validation |
|---|---|---|---:|---|
| D1 | Document client-strictness rationale in `architecture.md` (if C1 rejected) | v2 F7 | +1 paragraph | `make docs-links`; `make check` |

## 9. Summary

The codebase is disciplined and, for its feature set, already lean. The two
largest structural simplifications — dropping the supervisor pipeline or
collapsing the HTTP boundary — are off the table by operator decision and were
the only paths to large LOC reductions. With them removed:

- **Track A (≈555–750 LOC)** is the no-regret baseline: v2's consolidation
  findings, all re-verified unaddressed. Do this regardless.
- **Track B (≈300–480 LOC)** is the new work this edition adds: simplification
  *inside* the kept supervisor pipeline, led by flattening `OperationRuntime`
  and — carefully — folding the three context-packing orchestrators.
- **Track C** is where the operator's "remove low-priority features" lever
  actually bites: the evals/simulation tree, not the product core. Trimming
  forensics/benchmark scaffolds while keeping the hard-invariant gate and the
  behavioral report yields **~3–4k LOC** of maintenance reduction at low risk
  to the deterministic gate.
- **No new backend dependencies** are warranted. The only library move this
  edition endorses is OpenAPI codegen for the *future browser client*, which is
  a frontend concern. Under the locked constraints, libraries still do not
  help the backend.

The operator's stated goal — "lean and maintainable," with "detailed logging
to identify issues at this stage" — is best served by Tracks A + B in
production and Track C in evals, preserving every product guarantee and every
safety gate.
