# Jung: target architecture and migration

**Recommendation:** retain the local Python/SQLite monolith, but reduce the therapeutic runtime to **conversation and session review**. A conversation produces patient-visible text. One retrospective call produces a source-linked review, next-session guidance, and, when warranted, a replacement treatment plan. Application code owns acceptance, provenance, completion, and recovery.

This is a proposed replacement architecture, not a description of implemented behavior. Prepared on **2026-09-06** against **`18d18898`**, branch `fix/phase-10-intake-completion`. No production code, database, model configuration, or existing assessment document was changed by this planning exercise. Existing canonical documents remain descriptions of the running implementation until the corresponding migration lands.

Revised on **2026-09-20** after review of the migration strategy. The original current-state analysis remains a dated inspection; the target below incorporates the revised decisions. One-call review and endpoint compatibility remain unproven until R0 admission.

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
| Intake | Brief conversational orientation, user-controlled completion, optional explicit self-report inputs; remove extraction-driven slot completion |
| Preferences | Start directly in intake with visible, editable English/supportive defaults; no SETUP stage; freeze session preferences at first accepted input |
| Style | One preferred method; delete numerical ranking and unused plans for every style |
| Retrospection | One bounded structured call, independently validated sections, one atomic commit; admit the compact schema before restructuring persistence |
| Source truth | Messages own wording; explicit user inputs own preferences/self-reports; interpretation stays labeled interpretation |
| Longitudinal continuity | Current plan + latest useful handoff + selected, dated source references + bounded recent conversation |
| Storage | Five tables: profile, sessions, messages, plans, memory references; review work status belongs to its session |
| Context | Full completed session within one fixed product envelope; complete recent exchanges; active anchors, explicit recall, then recent memory references; lexical retrieval only after measured need |
| Configuration | Keep pydantic-settings/.env; simplify endpoint and call-policy types after six tasks become two; no TOML commitment |
| Structured output | Target json_schema only after intended llama.cpp/MTPLX configurations pass admission; any alternative needs a named requirement |
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
| R0 | Requirements, warning-free baseline, compact one-call review and endpoint admission spike | None |
| R1 | Model-boundary correctness: finish, deadlines, caps, credentials, cancellation | R0 admission |
| R2 | Breaking therapeutic/storage cutover, reviewed as a stack on an integration branch | R1 |
| R3 | Remove residual obsolete evidence machinery; keep only surviving hard contracts | R2 |
| R4 | Standard logging and explicit sensitive capture/export | R3 |
| R5 | Simplify two-task configuration and admitted structured parsing | R4 |
| R6 | Historical selection and source inspection at 100-session scale | R5 |
| R7 | Historical executable retirement, documentation, final acceptance | R6 |

R2 uses stacked reviewable PRs or individually reviewed commits on a short-lived integration branch. Intermediate branches need not be supported releases. Merge the complete vertical flow into main only after its gates pass; one development-database reset replaces compatibility adapters. Retire extraction-specific assertions with extraction itself, and add surviving source-retention/next-context tests in the same cutover. Do not rebuild old forensics before deleting their owner.

## Acceptance and limits

The target must demonstrate a successful two-session journey, source traceability through a later correction, atomic failure/retry behavior, useful anchor/explicit-recall continuity, and bounded prompts. R0 tests the single review call on 6–10 frozen completed-session cases before production restructuring. If the intended local reviewer cannot produce useful valid output within one correction, revise the schema or call design before proceeding. No production flag maintains competing pipelines.

Large-history deterministic fixtures are cheap and required. Long live journeys and repeated model benchmarks are not routine gates. No live model was exercised to validate this proposed architecture. See the planning-deliverable validation record in the [migration plan](06-migration-plan.md) for checks of these documents.
