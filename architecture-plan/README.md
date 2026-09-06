# Jung: target architecture and migration

**Recommendation:** retain the local Python/SQLite monolith, but reduce the therapeutic runtime to **conversation and session review**. A conversation produces patient-visible text. One retrospective call produces a source-linked review, next-session guidance, and, when warranted, a replacement treatment plan. Application code owns acceptance, provenance, completion, and recovery.

This is a proposed replacement architecture, not a description of implemented behavior. Prepared on **2026-09-06** against **`18d18898`**, branch `fix/phase-10-intake-completion`. No production code, database, model configuration, or existing assessment document was changed by this planning exercise. Existing canonical documents remain descriptions of the running implementation until the corresponding migration lands.

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
| Style | User preference chosen before initial review; delete numerical ranking and unused plans for every style |
| Retrospection | One bounded structured call, independently validated sections, one atomic commit |
| Source truth | Messages own wording; explicit user inputs own preferences/self-reports; interpretation stays labeled interpretation |
| Longitudinal continuity | Current plan + latest useful handoff + selected, dated source references + bounded recent conversation |
| Storage | Five tables: profile, sessions, messages, plans, memory references; review work status belongs to its session |
| Context | Full completed session for review; complete recent exchanges for conversation; deterministic historical selection with reserved space |
| Reliability | SDK retries disabled; at most one semantic/schema correction; explicit timeout, truncation, cancellation, and recovery behavior |
| Observability | Standard structured logging; separately enabled sensitive payload capture; database export on explicit request |
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
| M0 | Baseline, contract inventory, frozen synthetic comparison cases | None |
| M1 | Make evaluation evidence small and owned by tests | M0 |
| M2 | Standard logging and explicit sensitive capture/export | M1 |
| M3 | Simplify and harden the model boundary and configuration | M2 |
| M4 | One breaking therapeutic/storage cutover: intake, review, plans, review lifecycle, basic context | M3 |
| M5 | Finish historical selection and source inspection at 100-session scale | M4 |
| M6 | Retire superseded infrastructure, consolidate documentation, accept the target | M5 |

M4 is deliberately broader than the others: the obsolete intake, assessment, operation, and review concepts refer to one another. One coherent cutover and a development-database reset are simpler than compatibility adapters. Its implementation is split into reviewable commits, but the branch is integrated only when the vertical flow works.

## Acceptance and limits

The target must demonstrate a successful two-session journey, source traceability through a later correction, atomic failure/retry behavior, meaningful historical recall, and bounded prompts. The single review call is an admission hypothesis: if the intended local review model cannot reliably fill the compact schema after one correction, reconsider that decision rather than silently maintaining two production pipelines.

Large-history deterministic fixtures are cheap and required. Long live journeys and repeated model benchmarks are not routine gates. No live model was exercised to validate this proposed architecture. See the planning-deliverable validation record in the [migration plan](06-migration-plan.md) for checks of these documents.
