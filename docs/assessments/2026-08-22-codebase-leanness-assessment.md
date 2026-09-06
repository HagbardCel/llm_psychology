# Codebase Leanness and Maintainability Assessment

> Assessment date: 2026-08-22. Scope: the entire `jung` repository as of
> commit `c62b7c2` (Phase 8C cost-bounded validation). This is a point-in-time
> advisory document. It does not change any contract in the canonical
> documentation ([Architecture](../architecture.md),
> [Workflow](../workflow.md), [Database](../database.md),
> [API v1](../api-v1.md)); where it discusses changing behavior, the change
> becomes real only when implemented, tested, and synced into the owning
> canonical document.

## 1. Purpose and method

The product goal is a functional, lean, maintainable codebase for one user on
one laptop. This assessment:

1. measures where code and complexity actually live;
2. identifies concrete improvement opportunities (correctness-neutral
   simplifications, duplication, over-defense);
3. evaluates — honestly and against the project dependency policy — whether
   third-party libraries or higher abstractions would make parts leaner;
4. lists what should deliberately **not** be changed;
5. proposes a prioritized, validation-aware action plan.

Method: full read of all seven canonical docs plus `tests/README.md` and
`evals/README.md`; line-level review of the largest production modules
(persistence, LLM adapter, API client, chat runtime, application, config,
diagnostics, client console); structural greps for duplication and diagnostic
call-site density; test-suite layout review.

## 2. Project profile

### 2.1 Size

| Area | Python LOC | Notes |
|---|---:|---|
| `src/jung` production | 14,069 | incl. ~2,250 top-level modules (application, config, diagnostics, workflow, composition) |
| `tests/` | 29,158 | 74 test files; deterministic only |
| `evals/` | 7,024 | opt-in real-model surfaces + simulation harness |

Largest production modules:

| Module | LOC | Share of src |
|---|---:|---:|
| `persistence/sqlite_store.py` | 1,237 | 8.8% |
| `llm/openai_compatible.py` | 849 | 6.0% |
| `client/api_client.py` | 693 | 4.9% |
| `_application/chat.py` | 592 | 4.2% |
| `application.py` | 590 | 4.2% |
| `client/console.py` | 560 | 4.0% |
| `diagnostics.py` | 530 | 3.8% |

Package distribution: `phases/` 3,559 · `llm/` 1,767 · `api/` 1,585 ·
`persistence/` 1,519 · `client/` 1,422 · `_application/` 1,312 · `domain/`
597 · top-level 2,248.

### 2.2 Dependencies

Seven runtime dependencies: `openai`, `pydantic`, `pydantic-settings`,
`fastapi`, `uvicorn`, `httpx`, `prompt-toolkit`. Dev: `ruff`, `pytest`,
`pytest-asyncio`. Zero TODO/FIXME markers in `src/jung`.

### 2.3 Health signals

- Canonical documentation is complete, current, and cross-linked; `make check`
  enforces doc links.
- Test ownership doctrine ("one exhaustive owning layer per invariant") is
  documented and visibly followed; unit/integration/e2e layers are separated.
- No dead-feature speculation found: every module maps to a documented
  product behavior.
- Hygiene is clean (gitignore covers local tooling state; no stray tracked
  artifacts).

**Verdict up front:** this codebase is already unusually lean relative to its
feature set. The remaining bulk is *product logic* (therapeutic phases,
prompt projection) and *deliberate strictness* (protocol validation,
diagnostics redaction, cancellation safety). There is no large win available
from swapping in libraries. The realistic improvement budget identified below
is roughly **250–400 LOC (~2–3% of `src/jung`) plus several robustness wins**
— worth doing, but as consolidation, not restructuring.

## 3. Strengths to preserve

1. **Derived workflow stage** (`workflow.py`, 242 LOC): pure functions over
   durable facts; impossible states raise instead of being repaired. No
   second workflow-state projection exists anywhere.
2. **One store, explicit SQL, explicit transactions**
   (`sqlite_store.py`): `BEGIN IMMEDIATE` boundaries live in exactly one
   class; multi-table use cases commit atomically in single methods.
3. **Jung-owned structured output** with at most one correction attempt and
   `max_retries=0`: physical attempt semantics are legible and tested.
4. **Request-owned chat streaming**: durable truth is messages only; the
   cancellation-shielding dance in `_application/chat.py` is intricate but
   each piece serves a documented recovery semantic.
5. **Diagnostics discipline**: three separate switches, redaction of
   credentials, private file modes, best-effort capture that can never alter
   application outcome.
6. **Documentation sync culture**: AGENTS.md's doc-sync table is actually
   honored in the code seen during this review.

## 4. Findings — internal simplification (no new dependencies)

Findings are ordered by expected value-to-effort ratio. None changes external
behavior unless explicitly stated.

### F1 — Deduplicate provider error classification and evidence recording in the LLM adapter

**Evidence:** `llm/openai_compatible.py` contains two near-identical
try/except ladders. In `stream_text`, five except blocks
(`asyncio.CancelledError`, `APITimeoutError`, `APIConnectionError`,
`APIStatusError`, generic `Exception`) repeat the same ~10-line body:
set `status` / `error_type` / `error_message`, call
`_record_provider_failure(...)` with identical argument shapes, re-raise a
classified error. `_make_provider_request` repeats the same ladder again.

**Cost:** ~150–200 lines, and a real drift risk — the two ladders have already
subtly diverged (e.g., `InvalidLLMOutput` handling appears only in the
non-streaming path).

**Recommendation:** extract one classification table
(`exception type → (status, error_type, classifier)`) plus a single
context-manager or helper that owns "record failure + classify + raise".
Reuse the existing `_classify_status_error`. Expected saving: **80–120 LOC**
and one semantic instead of five copies.

**Validation:** focused adapter tests (`tests/unit/llm/test_openai_adapter.py`)
already enumerate timeout/connection/status/cancel branches; `make check`.

### F2 — Unify the three shield-and-drain implementations

**Evidence:** cancellation-safe awaiting of an owned task is implemented three
times with the same shape (`create_task → shield → drain_cancelled_task →
distinguish completed-during-cancel from failed-during-cancel`):

- `_application/store_calls.run_store_call`;
- `_application/chat._persist_user_message_drained` (raises
  `_AcceptedDuringCancel` when persistence won);
- `_application/chat._await_owned_terminalization` (raises
  `_TerminalDuringCancel`).

`_async_cleanup.drain_cancelled_task` is shared, but the surrounding
bookkeeping is triplicated.

**Recommendation:** one helper, e.g.
`await_owned(task, *, on_completed_during_cancel)` in `_async_cleanup.py`,
used by all three call sites. Expected saving: **40–60 LOC** and, more
importantly, a single place to reason about the hardest concurrency semantics
in the repo. Do not switch wholesale to `asyncio.TaskGroup` — the required
"completed during cancellation" distinction is custom and TaskGroup does not
express it more clearly than the unified helper would.

**Validation:** existing cancellation tests across
`tests/unit/application/`, `tests/integration/api/` (NDJSON disconnect cases)
are the owning layer; `make check`.

### F3 — Fuse JSON payload validation into serialization in the persistence layer

**Evidence:** `persistence/_sqlite_support.validate_json_mapping` +
`_validate_json_value` (~95 lines) recursively pre-validate mappings before
`json_dumps` (finite numbers, string keys, no circular refs). Every validated
payload is immediately serialized by `sql.json_dumps` in the same call path
(`intake_record`, assessment `result`, post-session `result`). `json.dumps(…,
allow_nan=False)` already raises on non-finite floats and circular references;
the only extra behavior is rejecting non-string mapping keys, which is a
~5-line key check.

**Recommendation:** replace validate-then-dump with dump-and-translate: one
function that calls `json_dumps` inside `try/except (ValueError, TypeError)`
and raises `InvariantViolation` with the field name. Expected saving:
**70–90 LOC**. Behavior preserved because serialization is the operation that
defines JSON-compatibility here.

**Validation:** owning layer is `tests/integration/store/`; keep the existing
malformed-payload cases (NaN, circular reference, non-string keys) green;
`make check`.

### F4 — Remove the duplicated `UtcDateTime` annotation

**Evidence:** `_as_utc` + `UtcDateTime = Annotated[AwareDatetime,
AfterValidator(_as_utc)]` are defined identically in both
`domain/models.py:22` and `api/contracts.py:19`.

**Recommendation:** define once in `domain/models.py` (or a tiny shared
annotation module) and import in contracts. The dependency direction
(`api → domain`) already permits this. Trivial LOC saving, but removes a
silent divergence risk if timezone normalization ever changes.

**Validation:** `make check`.

### F5 — Named-access row codecs in the persistence layer

**Evidence:** all `row_to_*` helpers in `_sqlite_support.py` index tuples
positionally (`row[0]` … `row[12]`). A column reorder in any SELECT silently
corrupts typed models; correctness currently rests on careful pairing of four
SELECT constants with four mappers.

**Recommendation:** either select into `sqlite3.Row` and read by column name,
or add a tiny `columns → model` mapping table next to each SELECT constant.
Neutral on LOC (+10–20), but converts a whole class of latent bugs into
KeyErrors. This is the highest robustness-per-line change in the report.

**Validation:** owning layer is `tests/integration/store/`; `make check`.

### F6 — Trim config parsers where pydantic-settings already suffices

**Evidence:** `config.py` (412 LOC) carries ~150 lines of hand-written
`BeforeValidator` parsers. Some enforce genuine strictness beyond library
defaults (JSON-object-only fields, NaN rejection, wildcard-CORS refusal,
streaming-task structured-mode restriction) — keep those. Others duplicate
what pydantic-settings already handles well (path trimming, log-level
normalization could drop to `Annotated[str, Field(pattern=...)]`-style
declarations).

**Recommendation:** low-priority cosmetic pass; do not weaken deliberate
strictness (tight bools, finite-number rejection are intentional). Expected
saving: **30–60 LOC**. Only worthwhile when `config.py` is next touched for a
real feature.

**Validation:** `tests/unit/**/test_api_settings.py` and config-focused tests
own this surface; `make check`.

### F7 — Client protocol strictness: document the trade-off, optionally narrow it

**Evidence:** `client/api_client.py` spends roughly 300 of its 693 lines on
defensive protocol machinery: a 12-member `ProtocolErrorKind` taxonomy,
sanitized nested-validation-issue reporting, request-ID echo verification
including recursive scans for nested `ErrorEnvelope`s, an error-code↔HTTP-status
cross-check table, media-type checks, and stream-event correlation checks.

This validates a loopback HTTP conversation between two components that ship
in the *same package and version*. The strictness duplicates protection that
`tests/integration/client/` and the console E2E probe already provide, but it
also converts silent contract drift into loud fail-fast errors at runtime —
consistent with the "Foundation failures" rule (no hidden fallbacks).

**Options:**

1. **Keep as is** (defensible; zero effort). If kept, record one paragraph in
   `architecture.md` stating that the client is intentionally a runtime
   contract monitor, so future contributors do not "simplify" it by accident.
2. **Narrow** to: decode + request-ID echo check + typed error raise
   (~150–250 LOC saved), leaving deeper drift detection to integration tests.

**Recommendation:** Option 1 with documentation. The cost is bounded, the
behavior is tested, and removal would reduce fail-fast coverage that the
product philosophy explicitly favors. Revisit only if the client grows new
routes.

**Validation:** if changed: `tests/unit/client/`, `tests/integration/client/`,
`probe-console`; otherwise none.

## 5. Third-party library analysis

Evaluated against the AGENTS.md dependency policy: *add a dependency only when
it removes a meaningful Jung-owned responsibility; which Jung code
disappears?*

| Candidate | Would replace | Verdict |
|---|---|---|
| SQLAlchemy / SQLModel / ORM | `SQLiteStore` SQL + codecs | **No.** Forbidden by architecture constraints; the store's explicitness *is* the design (transaction boundaries, DDL-enforced invariants). An ORM deletes little of the 1,519 LOC — most of it is workflow-coupled mutation logic, not plumbing. |
| Instructor / pydantic-ai / LangChain / Outlines | structured-output loop | **No.** Forbidden: structured output is Jung-owned; the correction-attempt semantics (`max_retries=0`, one explicit correction) are product contracts. Wrappers would add shim machinery without deleting the semantic validator. Pydantic-ai is the closest call of the ten candidates; see Appendix A for the full evaluation and re-evaluation triggers. |
| openapi-python-client / datamodel-code-generator | DTOs + typed client | **No.** Contracts are hand-curated, shared between server and client in-package; NDJSON streaming, request-ID correlation, and event ordering would remain hand-written anyway. Codegen adds a build pipeline for marginal gain. |
| structlog / OpenTelemetry | diagnostics/logging | **No.** The 530 LOC own redaction, private file modes, best-effort latching, and schema-v5 events — product safety requirements no library provides. OTel is architecturally disproportionate for a local-first tool. |
| Tenacity | retry logic | **No.** Retries are intentionally absent (fail-fast foundation rule). Adding a retry library would contradict the product. |
| Textual / Rich | console rendering | **No.** The console's Protocol-based I/O ports (`InputProvider`, `ConsoleOutput`) already give full testability with plain `print`; a TUI framework adds weight against the leanness goal. |
| Typer / Click | three small CLIs | **No.** argparse usage totals ~60 lines across entry points. |
| anyio / Trio adapters | asyncio runtime | **No.** Forbidden (one asyncio runtime). |
| httpx-sse / sse-starlette | NDJSON streaming | **No.** Transport is NDJSON lines over ordinary HTTP; `response.aiter_lines()` is already the minimal implementation. |
| pytest-httpx / respx | test transport | **No.** Tests deliberately use the real ASGI app / real transport; mocking at the socket layer would weaken the ownership doctrine. |

**Conclusion:** the current dependency set is right-sized. Every remaining
large module owns either therapeutic product logic or a documented safety /
contract property. Leanness gains must come from internal consolidation
(Section 4), not from adoption. This outcome is itself worth recording: the
dependency-policy checklist was applied to ten plausible candidates and none
survived question 3 ("which Jung code disappears?").

## 6. Higher-abstraction opportunities (standard library only)

Beyond F1–F3, three abstraction moves reduce code without dependencies:

1. **Single owned-task await helper** (see F2) — the highest-value abstraction
   in the repo because it concentrates cancellation semantics.
2. **Table-driven provider-error classification** (see F1) — replaces two
   exception ladders with one declarative mapping.
3. **Declarative row-codec tables** (see F5) — pairs SELECT columns with
   model fields in one visible place per aggregate.

Deliberately **not** recommended: introducing a generic "processor base
class" for phases. The four processors share little shape (streaming vs.
structured outputs differ fundamentally); a common abstraction would be
speculative generality, which the architecture explicitly minimizes.

## 7. Observations outside `src/jung`

1. **Test volume (29k vs 14k production LOC).** High, but justified by the
   ownership doctrine; the risk to watch is higher-layer tests re-deriving
   lower-layer case matrices — precisely what `tests/README.md` already
   forbids. No action beyond continued vigilance during review.
2. **Evals infrastructure weight (7k LOC + phase8b/phase8c protocols).** These
   are the product's behavioral quality instrument and are correctly opt-in.
   Suggestion: once a phase protocol reaches its frozen OUTCOME and its
   conclusions stop informing new work, consider moving operator scripts to a
   clearly-labeled archive section rather than growing parallel protocols.
3. **Per-mutation snapshot-fact derivation.** Every mutating store call
   re-runs `load_snapshot_facts` (~6 queries) via `_require_stage`. At local
   SQLite scale this is microseconds; recorded here as an accepted trade-off
   so nobody "optimizes" it into a cache (which would reintroduce a stale-state
   projection the design deliberately avoids).

## 8. What must not change

- Message-native chat truth and request-owned streaming semantics.
- Store-owned transaction boundaries and DDL-enforced invariants (schema v7).
- Structured-output ownership, single-correction semantics, `max_retries=0`.
- Diagnostic capture being strictly best-effort and side-effect-free.
- Fixed two-role LLM routing defined in source.
- The no-migration, reset-the-database stance.

## 9. Prioritized action plan

| # | Action | Type | Est. effect | Validation (per AGENTS.md matrix) |
|---|---|---|---|---|
| 1 | F5 named-access row codecs | robustness | +15 LOC, kills a bug class | focused store tests + `make check` |
| 2 | F1 adapter error-ladder dedup | dedup | −80–120 LOC | `tests/unit/llm/` + `make check`; `make smoke-local-llm` when a server is available (adapter/provider change) |
| 3 | F3 fuse JSON validation into serialization | simplification | −70–90 LOC | focused store tests + `make check` |
| 4 | F2 unified owned-task await helper | dedup | −40–60 LOC | cancellation-focused unit/integration tests + `make check` |
| 5 | F4 shared `UtcDateTime` | dedup | −8 LOC | `make check` |
| 6 | F7 option 1: document client strictness rationale in `architecture.md` | docs | +1 paragraph | `make docs-links` while editing; `make check` before merge |
| 7 | F6 config parser trim | cosmetic | −30–60 LOC | settings tests + `make check` (defer until `config.py` is next touched) |

Items 1–5 together: ≈ −200–280 LOC net, zero behavior change intended, and a
material reduction in duplicated concurrency/error-handling semantics. Items
6–7 are opportunistic.

None of these require schema changes, API contract changes, or new
dependencies; none touch therapeutic phase logic.

## 10. Summary

The repository demonstrates that "lean" here is a property of disciplined
scope, not of minimal line count: strict protocol validation, cancellation
safety, and diagnostics exist because single-user software still deserves
fail-fast correctness and auditable failures. The dependency analysis confirms
the current seven-dependency stack is optimal under the project's own policy.
The concrete recommendations above consolidate duplicated machinery, harden
the persistence codec boundary, and document one deliberate trade-off —
keeping the codebase lean without touching a single product guarantee.

## Appendix A — pydantic-ai detailed evaluation

This appendix records the full reasoning behind the rejection of
[pydantic-ai](https://ai.pydantic.dev) so that a future redesign can start
from this analysis instead of repeating it. Pydantic-ai is the strongest of
the ten candidates evaluated in Section 5: it is Pydantic-native, actively
maintained, and its core feature — typed structured outputs with validation
and retry — targets exactly what `jung.llm.structured` and
generate_structured already do.

### A.1 Candidate replacement surface

What pydantic-ai would nominally replace:

- `llm/structured.py` (248 LOC): schema instruction building for `prompt`
  mode, `response_format` construction for `json_schema` / `json_object`
  modes, markdown-fence stripping, structured-text validation,
  correction-message assembly;
- parts of `llm/openai_compatible.py`: the validation/correction loop inside
  `OpenAICompatibleLLM.generate_structured` (~150–250 LOC of its 849).

Gross deletion potential: roughly **400–500 LOC**.

### A.2 What does not disappear

Applying dependency-policy question 3 ("which Jung code disappears?"):

1. **The gateway protocol itself.** Architecture requires that provider types
   never leak into domain, application, phase, API, or client code. The
   project-owned `LLMGateway` protocol (`stream_text` /
   `generate_structured`) must remain the anti-leak boundary, with a new
   wrapper adapting pydantic-ai agents and message types to it — new shim
   code replacing deleted code.
2. **Diagnostics evidence capture (~300 LOC of the adapter).** Jung records
   `llm.provider.request/response/error` events with redaction,
   provider-attempt correlation IDs, latency, token usage, and correction
   triggers into its schema-v5 DiagnosticRecorder. Pydantic-ai's
   instrumentation is oriented at OpenTelemetry/Logfire. Mapping its hooks
   onto Jung's event vocabulary remains Jung-owned code of comparable size to
   what was deleted.
3. **The error taxonomy.** Jung classifies transport failures into
   `LLMUnavailable` / `LLMTimeout` / `LLMProtocolError` / `InvalidLLMOutput`,
   which drive public error codes and retryability decisions on durable
   operations. Translating pydantic-ai's exception set is another adaptation
   layer.
4. **Policy and role routing.** `ModelPolicy`, task overrides, and the
   source-defined SESSION/SUPERVISOR role split are Jung-owned by design and
   unaffected.

Net effect on LOC: close to a wash — plausibly −400 gross, +250–350 of
wrapper, instrumentation, and translation code.

### A.3 Decisive conflicts

**Physical-attempt semantics.** AGENTS.md states: "Do not enable a hidden
provider, wrapper, or SDK retry layer that changes physical-attempt
semantics." Jung's contract is `max_retries=0` on the SDK client, exactly one
explicit correction attempt on invalid output, and provider transport
failures that never trigger validation correction. Pydantic-ai's core loop
ships its own configurable retry machinery (model retries, output retries).
Preserving Jung's exact attempt accounting would require auditing every
framework default and pinning them with tests — and even then the semantics
live in framework source, not in Jung's repository. The property "one
correction, transport failures propagate" is currently ~50 legible lines in
generate_structured; under pydantic-ai it becomes a configuration claim about
an external system. This alone approaches disqualification.

**Agent-framework exclusion.** The architecture explicitly excludes agent
frameworks and tool calling as application assumptions. Jung would consume
only pydantic-ai's structured-output slice, but adoption imports the
agent/tool/dependency-injection abstraction wholesale — concepts with no Jung
use case, plus a fast-moving dependency surface to track across upgrades.

### A.4 The steelman, and why it still loses

Structured-output handling across OpenAI-compatible servers is genuinely
fiddly: providers that ignore `response_format`, reasoning models that wrap
JSON in fences, prompt-mode instruction drift. Pydantic-ai hardens exactly
these edges, and outsourcing that maintenance has real value. Three factors
blunt it here:

- Jung's edge-case surface is small and already pinned by deterministic tests
  (`tests/unit/llm/test_structured_output.py`, adapter tests). The scenarios
  are stable because the provider contract is fixed: Chat Completions, three
  structured modes, no tools, no streaming-structured output.
- The hard evals assert model invariants such as exact-value instruction
  resistance through Jung's correction loop. The loop's behavior is part of
  the evaluated product surface, not incidental plumbing; moving it into a
  library changes what that evidence measures.
- Strictness asymmetry: pydantic-ai optimizes for obtaining valid output with
  minimal fuss; Jung optimizes for accounting every physical attempt and
  recording evidence. These goals pull in different directions.

### A.5 Verdict and re-evaluation triggers

Rejected on dependency-policy questions 3 and 5 (insufficient Jung code
disappears; shim machinery introduced), with a direct collision on the
no-hidden-retry rule and the agent-framework exclusion. It is the closest
call among the evaluated candidates.

Re-evaluate pydantic-ai only if the product deliberately adopts one or more
of the following, each of which currently has no demonstrated requirement:

- tool calling / function-calling workflows;
- multi-provider routing beyond the two fixed roles;
- agent-style loops (model-driven multi-step behavior);
- structured streaming outputs.

Any such adoption must still preserve the physical-attempt semantics above
(`max_retries=0`, one explicit correction, transport failures propagate) and
must be recorded first as a change to the canonical safety/architecture
contracts, per the project's product-decision rules.
