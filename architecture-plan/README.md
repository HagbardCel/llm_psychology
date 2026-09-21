# Jung: target architecture and migration

**Recommendation:** retain the local Python/SQLite monolith, but reduce the therapeutic runtime to **conversation and session review**. A conversation produces patient-visible text. One retrospective call produces a source-linked review, next-session guidance, and, when warranted, a replacement treatment plan. Application code owns acceptance, provenance, completion, and recovery.

This is a proposed replacement architecture, not a description of implemented behavior. Prepared on **2026-09-06** against **`18d18898`**, branch `fix/phase-10-intake-completion`. No production code, database, model configuration, or existing assessment document was changed by this planning exercise. Existing canonical documents remain descriptions of the running implementation until the corresponding migration lands.

Revised on **2026-09-21**, including PR #77 feedback on executable stack boundaries, independent confirmation cases, and limiting feature scope. The current-state analysis describes main at **`73492a5b`**; the original Phase-10 inspection and its evidence remain historical. Implementation starts from then-current main without requiring PR #76 to merge or close. One-call review remains unproven until R0b admission on the corrected R1 boundary.

## Read the plan

1. [Current implementation and traced flows](01-current-state.md)
2. [Problems, alternatives, and decisions](02-problems-and-design-options.md)
3. [Target runtime, workflows, and model boundary](03-target-architecture.md)
4. [Data ownership, context, and a longitudinal example](04-data-and-context-model.md)
5. [Observability, safety, evaluation, and performance](05-observability-and-evaluation.md)
6. [Executable migration and simplification ledger](06-migration-plan.md)

The recommendations are engineering judgments informed by source inspection. They are not evidence of therapeutic effectiveness. Proposed model behavior must pass the targeted acceptance work in the migration plan.

## Important decisions

| Decision | Recommendation |
|---|---|
| Deployment | One asyncio backend, one SQLite database, one console using the existing HTTP boundary |
| Therapeutic actors | Two responsibilities, not an agent society: live conversation and retrospective review |
| Model topology | One configured model by default; optional second review endpoint, with explicit credentials and capabilities |
| Intake | Free-text orientation and user-controlled completion; remove extraction-driven completion; defer typed self-report controls pending an independent product need |
| Method/language settings | English language default and initially unselected method; no SETUP stage; profile alone owns method; sessions preserve only scalar language for review/retry |
| Style | Choose a packaged method during intake; Finish Intake requires a valid choice and makes it immutable; delete numerical ranking and unused plans; defer post-intake switching |
| Retrospection | One bounded structured call, independently validated sections, one atomic commit; admit the compact schema before restructuring persistence |
| Source truth | Messages own wording; profile owns method and default language; sessions own their language; interpretation stays labeled interpretation |
| Longitudinal continuity | Current plan + latest useful handoff + selected, dated source references + bounded recent conversation |
| Storage | Five tables: profile, sessions, messages, plans, memory references; review work status belongs to its session |
| Context | One source serializer for byte accounting and full-session review; handoff anchors and recent references measured in R6; recall only if justified as optional R6a; no older review notes or purpose ranking |
| Configuration | Keep pydantic-settings/.env; simplify endpoint and call-policy types after six tasks become two; no TOML commitment |
| Structured output | Target json_schema on one designated required review runtime; each additional advertised runtime needs separate admission; any alternative mode needs a named requirement |
| Reliability | SDK retries disabled; at most one semantic/schema correction; explicit timeout, truncation, cancellation, and recovery behavior |
| Observability | Standard structured logging; separately enabled sensitive payload capture; explicit database export; no operational log consumer is a correctness dependency |
| Evaluation | Deterministic gate, small endpoint/model admission checks, focused qualitative replays, occasional short journeys |

## Largest simplifications

- Delete the intake extraction/materialization/merge/completeness chain. A model's ability to fill a record should not determine whether the user can proceed.
- Delete assessment style scores and three speculative initial plans. Generate one plan for the chosen method.
- Replace analysis → evidence resolution → update with one review. Delete the special update-context format and its packing machinery.
- Replace generic assessment/post-session operations with a session's single review lifecycle. Preserve durable recovery and atomic commit semantics.
- Replace rich-to-minimal character-budget searches with bounded documents and straightforward whole-item packing. Stop silently reviewing only a selected fraction of a completed session.
- Replace the production diagnostic recorder, wrapper gateway, and automatic shutdown snapshot with ordinary logging and opt-in payload capture. Retain small test-owned evidence only when an assertion needs it.
- Retire historical experiment executables and general forensic reconstruction. Keep useful synthetic scenarios and historical outcome documents.

These changes intentionally remove some behavior: automatic intake completeness, style suitability scores, exact two-pass review evidence contracts, and automatic full-database debug copies. Their underlying useful requirements have explicit replacements in the detailed plan.

## Migration sequence

| Phase | Coherent change | Main dependency |
|---|---|---|
| B0 | Refresh main inventory and baseline; separately fix the coroutine warning if reproduced | None |
| R0a | Minimal schema, development cases and confirmation requirements, frozen rubric, canonical runtime selection | B0; can overlap R1 |
| R1 | Model-boundary correctness: finish, deadlines, caps, credentials, cancellation | B0; independent of architecture admission |
| R0b | Freeze candidate; pass full development rerun before independent confirmation construction/execution | R0a + R1 |
| R2a–R2e | Explicit schema/store → conversation/workflow → review/context → API/console → retirement stack | R1 + successful R0b |
| R3 | Remove residual obsolete evidence machinery; keep only surviving hard contracts | R2 |
| R4 | Standard logging and explicit sensitive capture/export | R3 |
| R5 | Simplify two-task configuration and admitted structured parsing | R4 |
| R6 | Validate baseline continuity and performance at 100-session scale | Complete R2; independent of R3–R5 |
| Optional R6a / R6b | Explicit recall for demonstrated gaps; lexical retrieval only for remaining gaps | R6 evidence; neither is guaranteed work |
| R7 | Historical executable retirement, documentation, final acceptance | R5 + R6 + any selected evidence-backed extensions |

R2 uses named stacked PRs on `feat/architecture-cutover`, reviewed against their predecessors, with owning tests and a passing `make check` in each layer. Intermediate branches need not be supported releases. Introduce target primitives while retaining old persistence required by active callers; wire the complete replacement in R2d and remove superseded owners with their final callers. No dual writes or compatibility adapters. Only the complete validated stack targets main, with surviving source-retention/next-context contracts. Do not import Phase-10 forensics. Each schema change increments its version and resets a disposable database; optional R6a requires a later reset only if its recall feature is justified, under the same no-migrations policy.

After R2, R3 → R4 → R5 cleanup and R6 baseline measurement can proceed independently. R6 may use R3's cleaned harness without requiring it. Final acceptance joins both paths; optional feature work can wait until cleanup finishes. Reuse early R6 evidence unless intervening changes invalidate what it measured.

## Acceptance and limits

The target must demonstrate a successful two-session journey, source traceability through a later correction, atomic failure/retry behavior, useful anchor/recent-source continuity, and bounded prompts. R6 measures the baseline before any recall feature is selected. R0b tests one designated reviewer using R1 transport semantics: tune on 6–8 development cases, freeze the candidate including sampling/reasoning settings, and rerun the complete development set. Only after all pass, have a separate evaluator create 3–4 fresh confirmation cases without candidate outputs, then freeze and run them once each on the unchanged candidate. At most one correction is allowed per case. Confirmation-informed revisions require fresh cases. Check that a small plan change preserves unrelated relevant goals/cautions. If admission fails, revise the schema or call design before cutover; a small holdout does not prove general reliability. Optional runtimes do not block this gate, and no production flag maintains competing pipelines.

Large-history deterministic fixtures are cheap and required. Long live journeys and repeated model benchmarks are not routine gates. No live model was exercised to validate this proposed architecture. See the planning-deliverable validation record in the [migration plan](06-migration-plan.md) for checks of these documents.
