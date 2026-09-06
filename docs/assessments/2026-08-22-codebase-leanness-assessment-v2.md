# Codebase Leanness and Maintainability Assessment — Edition 2

> Assessment date: 2026-08-22. Scope: the entire `jung` repository as of
> commit `c62b7c2` (Phase 8C cost-bounded validation). This is a point-in-time
> advisory document. It does not change any contract in the canonical
> documentation ([Architecture](../architecture.md), [Workflow](../workflow.md),
> [Database](../database.md), [API v1](../api-v1.md)); where it discusses
> changing behavior, the change becomes real only when implemented, tested, and
> synced into the owning canonical document.
>
> This edition supersedes the same-day first edition
> ([2026-08-22-codebase-leanness-assessment.md](2026-08-22-codebase-leanness-assessment.md)).
> Every finding in both editions was re-verified line-by-line against source.
> Edition 2 corrects two over-optimistic estimates (F2, F3), one detail
> (§7.3), and adds ten verified findings (F8–F17) plus a substantially
> expanded test-suite and third-party analysis. The first edition remains in
> place unmodified for provenance.

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

Method: full line-level review of the largest production modules
(`persistence/`, `llm/`, `_application/`, `application.py`, `config.py`,
`diagnostics.py`, `api/`), plus five parallel module audits with line-level
evidence requirements covering the API adapter, application core, client
package, phases/domain/config/composition, and tests/evals/tooling. Every
finding below carries file:line evidence; estimates were cross-checked against
the actual code, not extrapolated.

### Changes from edition 1

| Item | Edition 1 | Edition 2 |
|---|---|---|
| F2 (owned-task await helper) | −40–60 LOC | **−25–40 LOC** (two of three sites are identical modulo one sentinel class; the third differs more) |
| F3 (JSON validation fusion) | "~95 lines; −70–90" | **68 lines (118–185); −50–60** (the non-string-key check must survive) |
| §7.3 snapshot-facts cost | "~6 queries" | **4 queries** (`sqlite_store.py:1074–1100`) |
| Findings count | F1–F7 | F1–F17 (adds application scaffolding, tracing internals, strict-schema double walk, chat context blocks, operations symmetry, API mapping/errors, phase packing, merge mechanics, diagnostics write path, composition fallback) |
| Library analysis | 10 candidates | unchanged verdicts, strengthened with new evidence (§5) |
| Test/eval observations | qualitative | quantified with LOC and consolidation estimates (§7) |

## 2. Project profile

### 2.1 Size

| Area | Python LOC | Notes |
|---|---:|---|
| `src/jung` production | 14,069 | incl. ~2,248 top-level modules (application, config, diagnostics, workflow, composition) |
| `tests/` | 29,158 | deterministic suite + opt-in smoke |
| `evals/` | 7,024 | opt-in real-model surfaces + simulation harness |

Test:production ratio ≈ 2.35:1 overall; deterministic suite (unit +
integration + e2e) ≈ 1.81:1.

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
`pytest-asyncio`. Zero TODO/FIXME/XXX/HACK markers in `src/jung` (verified).

### 2.3 Health signals

- Canonical documentation is complete, current, and cross-linked; `make check`
  enforces doc links.
- Test ownership doctrine ("one exhaustive owning layer per invariant") is
  documented and visibly followed; unit/integration/e2e layers are separated.
- No dead-feature speculation found: every module maps to a documented
  product behavior. No unused public methods in the client package.
- Hygiene is clean.

**Verdict up front:** this codebase is already unusually lean relative to its
feature set. The remaining bulk is *product logic* (therapeutic phases, prompt
projection) and *deliberate strictness* (protocol validation, diagnostics
redaction, cancellation safety). No large win is available from swapping in
libraries. The realistic improvement budget identified below is
**≈555–750 LOC (~4–5% of `src/jung`) of low-risk consolidation**, plus
**≈295–450 LOC of optional medium-risk consolidations** (phase packing,
merge mechanics, config trim) — worth doing as consolidation, not
restructuring.

## 3. Strengths to preserve

1. **Derived workflow stage** (`workflow.py`, 243 LOC): pure functions over
   durable facts; almost entirely cross-entity invariant assertions (e.g.,
   "therapy session `plan_id` must match profile's current plan",
   `workflow.py:204–207`) that no single table can express. Deleting any
   branch deletes a real invariant check.
2. **One store, explicit SQL, explicit transactions**
   (`sqlite_store.py`): `BEGIN IMMEDIATE` boundaries live in exactly one
   class; multi-table use cases commit atomically in single methods.
3. **Jung-owned structured output** with at most one correction attempt and
   `max_retries=0` (`openai_compatible.py:152`, correction loop `:540–620`):
   physical attempt semantics are legible and tested.
4. **Request-owned chat streaming**: durable truth is messages only; the
   cancellation-shielding dance in `_application/chat.py` is intricate but
   each piece serves a documented recovery semantic.
5. **Diagnostics discipline** (`diagnostics.py`, 531 LOC): structural
   redaction with token-metric allowlist (`:34–64`, `:148–248`), URL
   sanitization (`:128–138`), 0600 private-file creation (`:251–272`),
   SQLite backup-API snapshots (`:275–314`), fail-latched append-only
   `trace.jsonl` writer (`:317+`). Product-owned; no library provides this.
6. **Narrow phase processors**: each of the four processors has a genuinely
   different shape (assessment: one `generate_structured` with a
   `validate_result` lambda, `assessment/processor.py:21–31`; therapy: pure
   `stream_text` passthrough, `therapy/processor.py:25–29`; intake: patch →
   merge → completeness decision with streaming; post-session: two chained
   structured calls with evidence resolution between them,
   `post_session/processor.py:115–145`). A shared "runner" would be exactly
   the speculative framework the architecture forbids.
7. **Client/DTO sharing**: `jung.client.api_client` imports all wire types
   from `jung.api.contracts` (`api_client.py:22–41`); the client defines
   exactly one model of its own (`ProtocolValidationIssue`,
   `:139–143`). Zero duplicated DTO definitions.
8. **Documentation sync culture**: AGENTS.md's doc-sync table is honored in
   the code reviewed.

## 4. Findings — internal simplification (no new dependencies)

Findings are ordered roughly by expected value-to-effort ratio within two
risk tiers. Unless stated, none changes external behavior. Estimates are net
LOC in `src/jung`.

### Tier A — low risk, behavior-preserving

#### F1 — Deduplicate provider error classification in the LLM adapter (−80–120)

**Evidence:** `llm/openai_compatible.py` contains two near-identical
try/except ladders. In `stream_text`, five except blocks
(`asyncio.CancelledError`, `APITimeoutError`, `APIConnectionError`,
`APIStatusError`, generic `Exception`, `:372–464`) repeat the same ~10-line
body: set `status` / `error_type` / `error_message`, call
`_record_provider_failure(...)` with identical argument shapes, re-raise a
classified error. `_make_provider_request` repeats the ladder with six
blocks (`:777–809`), recording deferred to `finally` (`:812–831`).

The two ladders have already subtly diverged: `InvalidLLMOutput` handling
exists only in the non-streaming path (`:782–786`) — semantically correct
(streaming yields raw text), but a reader must reconstruct that fact.

**Recommendation:** one classification table
(`exception type → (status, error_type, classifier)`) plus a single helper
that owns "record failure + classify + raise"; reuse `_classify_status_error`
(`:110–117`). Expected saving **80–120 LOC** and one semantic instead of
eleven copies.

**Validation:** `tests/unit/llm/test_openai_adapter.py` already enumerates
timeout/connection/status/cancel branches; `make check`;
`make smoke-local-llm` when a server is available (adapter change).

#### F8 — Collapse the five command scaffolds in `application.py` (−80–100)

**Evidence:** `update_profile` (`:262–303`), `select_style` (`:305–353`),
`start_session` (`:355–387`), `end_session` (`:389–457`), and
`retry_operation` (`:459–524`) repeat an identical ~25-line frame:
`diag.record_command_started` → pre-lock `_reject_if_shutdown()` +
`_reject_if_generation_active()` → `async with self._mutation_lock:` → the
same two rejects again → `load_snapshot_facts` →
`workflow.require_command_allowed(...)` → body →
`record_command_completed` + `record_transition` → the same two-branch
except ladder (`_COMMAND_REJECT_TYPES` → `record_command_rejected`;
`Exception` → `record_command_error`). `end_session` and `retry_operation`
additionally duplicate the `operation.created`/`operation.retried`
`diagnostic_context` + `schedule`-in-`finally` block (~20 lines each), which
also appears in `recover_on_startup` (`:154–168`).

**Cost:** ~125 LOC of scaffolding; the reject/lock/ordering policy lives in
five places that can drift.

**Recommendation:** one async context manager, e.g.
`async with self._command_frame(CommandName.X) as frame:` that owns rejects,
lock, facts, stage capture, and the diagnostics outcome ladder, yielding the
facts/stage. Expected saving **80–100 LOC** and a single home for command
admission semantics.

**Validation:** `tests/integration/application/` (command admission, busy,
shutdown, rejection paths) is the owning layer; `make check`.

#### F13 — API adapter mechanical layer (−110–150)

Four sub-findings, all verified:

1. **`mapping.py` field-copy converters (~60–100 savable).** The converter
   family (`_profile_wire` `:81–88`, `to_operation_summary` `:125–142`,
   `to_session_summary` `:144–152`, `to_session_detail` `:154–169`,
   `to_message_response` `:171–181`, `to_plan_summary` `:183–191`,
   `to_plan_detail` `:193–208`, `to_snapshot_response` `:210–231`,
   `to_profile_response` `:233–245`, `to_style_options_response`
   `:247–267`) is predominantly field-for-field copying with `.value`
   enum-to-string casts. The wire/domain split itself is architecturally
   **forced** (Literal narrowing for OpenAPI, `extra=forbid`, hidden
   internals like `Session.review`, and the client importing
   `jung.api.contracts` as its only shared boundary) — keep the split. But a
   small generic helper (build DTO from `model_dump(mode="json")` of the
   domain object plus explicit per-DTO overrides for renamed/derived fields)
   deletes the mechanical bodies while keeping the boundary.
2. **`errors.py` redundant specs (−27–30).** The `InvariantViolation`,
   `PersistenceFailure`, and `DomainError` entries (`:88–114`) are
   byte-identical to `_DEFAULT_ERROR_SPEC` (`:117–122`), and `_error_spec`
   (`:125–129`) already falls through to the default. The three entries are
   dead weight. Also `to_error_response` (`:167–176`) does a pointless
   envelope → `model_dump` → `model_validate` round-trip; construct
   `ErrorResponse` from the spec directly.
3. **`app.py` lifespan redundancy (−8).** Double try/finally setting
   `state.application = None` plus a `runtime_exited` flag (`:145–165`); a
   `_request_id_from_request` fallback branch that middleware always
   satisfies.
4. **`routes.py` dependency repetition (−15).** `_context(request)` +
   `Depends(get_application)` repeated at 9 sites → annotatable router-level
   dependencies; `health()` re-implements `deps.get_application_from_state`
   inline (`routes.py:338–342`).

**Validation:** `tests/integration/api/` + `tests/unit/api/` own this
surface; `make check`.

#### F9 — Consolidate `tracing.py` internals (−60–80)

**Evidence:** `llm/tracing.py` (`ObservedLLMGateway`) is *not* redundant with
the adapter's provider-attempt events — it records call-granularity
lifecycle (`llm.call.started/completed/cancelled/failed`) while the adapter
records attempt-granularity evidence (`llm.provider.request/response/error`);
a `generate_structured` call maps to up to two provider attempts, and the
`llm_call_id ↔ provider_attempt_id` correlation is deliberate. But the two
gateway methods duplicate each other: parallel
status/`terminal_recorded`/`logger.error`/`_record` outcome blocks in
`stream_text` (`:97–163`) and `generate_structured` (`:221–274`); a dead
`finally: pass` (`:182–183`); a `status` variable in `generate_structured`
assigned at `:194`, `:222`, `:239` but never read.

**Recommendation:** one outcome-recording helper
(`_finish(kind, exc|None, started, extra_log_fields)`); delete the dead
`finally` and the unused variable. Expected saving **60–80 LOC** with the
two-layer observability design intact.

**Validation:** `tests/unit/llm/test_tracing.py` owns it; `make check`.

#### F11 — Chat runtime context blocks and terminalize pair (−50–70)

**Evidence:** `_application/chat.py` builds the same
`diagnostic_context(session_id=..., client_message_id=..., request_id=... if
... else None)` block at eight sites (`:142–146`, `:173–177`, `:206–210`,
`:219–223`, `:247–251`, `:342–346`, `:498–502`, `:539–543`) — ~40 LOC that
collapse into a `_turn_context(...)` helper. Separately,
`_terminalize_ordinary_drained` (`:473–512`) and
`_terminalize_final_intake_drained` (`:514–574`) share most of their
terminalize body (assistant id, store commit under mutation lock,
`chat.turn.completed` event, `ChatCompleted` assembly); the final-intake
variant adds facts capture, transition, and operation creation. A
parameterized single terminalize path saves a further ~25–35 LOC.

**Validation:** cancellation/terminalization tests in
`tests/unit/application/` and `tests/integration/api/test_chat_stream.py`;
`make check`.

#### F2 — Unify the shield-and-drain implementations (−25–40)

**Evidence:** cancellation-safe awaiting of an owned task is implemented
three times with the same shape (`create_task → shield →
drain_cancelled_task → distinguish completed-during-cancel from
failed-during-cancel`):

- `_application/store_calls.run_store_call` (`:30–49`) — logs and records
  the drained failure, re-raises the caller's cancellation;
- `_application/chat._persist_user_message_drained` (`:374–383`) — raises
  `_AcceptedDuringCancel(task.result(), cancellation)` on completion;
- `_application/chat._await_owned_terminalization` (`:576–588`) — identical
  body with `_TerminalDuringCancel`.

The latter two are literally identical except for the sentinel class.

**Recommendation:** one helper, e.g.
`await_owned(task, *, on_completed_during_cancel)` in `_async_cleanup.py`,
used by all three call sites. Expected saving **25–40 LOC** and — more
importantly — a single place to reason about the hardest concurrency
semantics in the repo. Do not switch wholesale to `asyncio.TaskGroup`: the
required "completed during cancellation" distinction is custom and
TaskGroup does not express it more clearly.

**Validation:** existing cancellation tests across `tests/unit/application/`
and `tests/integration/api/` (NDJSON disconnect cases); `make check`.

#### F3 — Fuse JSON payload validation into serialization (−50–60)

**Evidence:** `persistence/_sqlite_support.validate_json_mapping` +
`_validate_json_value` (`:118–185`, 68 lines) recursively pre-validate
mappings before `json_dumps` (finite numbers, string keys, no circular
refs). Every validated payload is immediately serialized by `sql.json_dumps`
in the same call path (`sqlite_store.py:389`, `:439`, `:523`).
`json_dumps` already uses `allow_nan=False` (`:108–115`), which rejects
non-finite floats; `json.dumps` also raises on circular references. The only
extra behavior the pre-validation adds is rejecting non-string mapping keys
— plain `json.dumps` would silently coerce `int` keys — worth a ~5-line
key-type check.

**Recommendation:** replace validate-then-dump with dump-and-translate: one
function calling `json_dumps` inside `try/except (ValueError, TypeError)`
and raising `InvariantViolation` with the field name, plus the key-type
check. Expected saving **50–60 LOC**. Behavior preserved because
serialization is the operation that defines JSON-compatibility here.

**Validation:** owning layer is `tests/integration/store/`; keep the
existing malformed-payload cases (NaN, circular reference, non-string keys)
green; `make check`.

#### F10 — Move the strict-schema post-transform assert out of production (−43)

**Evidence:** `llm/structured.py` walks every JSON-schema-mode payload twice:
`to_provider_strict_json_schema` (`:138–183`) transforms and already
enforces the subset (rejects unknown keys `:118–135`, strips metadata
`:150–154`, sets `required`/`additionalProperties` itself `:163–164`), then
`assert_valid_strict_provider_schema` (`:186–228`) re-walks the output to
assert what the transform just constructed. Its only production call site
is immediately after the transform (`response_format_for_mode`,
`:235–237`); it can only fail if the transform has a bug. Tests import it
directly (`tests/unit/llm/test_structured_output.py:13`).

**Recommendation:** keep the validator, drop the production call — the
assertion becomes a test-owned invariant of `to_provider_strict_json_schema`
(which the existing tests already exercise at `:44–46`, `:59–60`,
`:78–79`, `:93–94`). Expected saving **43 production LOC**; zero behavior
change because the transform's own rejections still fire.

**Validation:** `tests/unit/llm/test_structured_output.py`; `make check`.

#### F4 — Remove the duplicated `UtcDateTime` annotation (−8)

**Evidence:** `_as_utc` + `UtcDateTime = Annotated[AwareDatetime,
AfterValidator(_as_utc)]` are defined identically in `domain/models.py:22–26`
and `api/contracts.py:19–23`.

**Recommendation:** define once in `domain/models.py` and import in
contracts. The dependency direction (`api → domain`) already permits this.
Removes a silent divergence risk if timezone normalization ever changes.

**Validation:** `make check`.

#### F5 — Named-access row codecs in the persistence layer (+10–20, robustness)

**Evidence:** all `row_to_*` helpers in `_sqlite_support.py` index tuples
positionally (`row[0]` … `row[12]`, `:202–279`), and `sqlite_store.py` has
scattered positional reads (`:303–304`, `:409`, `:656`, `:755`, `:836`,
`:891`, `:1082–1086`). A column reorder in any SELECT silently corrupts
typed models; correctness rests on careful pairing of the SELECT constants
(`:53–90`) with the mappers.

**Recommendation:** select into `sqlite3.Row` and read by column name, or
add a small `columns → model` mapping table next to each SELECT constant.
Neutral-to-slightly-positive on LOC, but converts a whole class of latent
bugs into KeyErrors. This is the highest robustness-per-line change in the
report.

**Validation:** owning layer is `tests/integration/store/`; `make check`.

#### F12 — Operation runtime symmetry and ownership field (−25–40)

**Evidence:** `_application/operations.py` runs the assessment and
post-session branches as parallel structures — build input → process →
acquire lock → load facts → `complete_*` → `operation.completed` event →
`record_transition` (`:212–238` vs `:239–289`) — sharing ~20 lines of
identical completion bookkeeping that a small helper collapses.
Separately, ownership is tracked twice: `_operation_task` (the Task) and
`_operation_task_id` (UUID), both maintained in `schedule` (`:147–148`) and
`_clear_ownership` (`:66–71`), while the task's name already encodes the id
(`:92–93`).

**Recommendation:** shared complete-and-record helper; derive the id from
the task (closure or `get_name()`) and drop `_operation_task_id`. Expected
saving **25–40 LOC** and one fewer parallel invariant.

**Validation:** `tests/integration/application/test_application_operations.py`
and recovery tests; `make check`.

#### F16 — Diagnostics write-path dedup (−15–20)

**Evidence:** `diagnostics.py` maintains two parallel write paths:
`_write_line` (`:430–451`) sanitizes then delegates, while
`_write_line_locked` (`:459–476`) also sanitizes — one code path is
recoverable.

**Validation:** `tests/unit/test_diagnostics.py` +
`tests/integration/application/test_diagnostic_capture.py`; `make check`.

#### F17 — Composition fallback resolver (−10–15)

**Evidence:** `composition.py:191–209` repeats the same
`supervisor_value if set else session_value` chain five times for base_url /
model / api_key / extra_body / headers. A tiny resolver helper (or a derived
property on `JungSettings`) centralizes it.

**Validation:** `tests/integration/application/test_llm_role_composition.py`;
`make check`.

### Tier B — optional, medium risk (semantic surfaces)

These touch prompt content or therapeutic merge semantics. They are real
reductions but demand the owning deterministic tests plus, where the change
can affect therapeutic behavior, `make eval-report` when configured.

#### F14 — De-duplicate the three context-packing orchestrations (−150–250)

**Evidence:** `context_projection.py` is a genuinely lean shared layer
(`_compact_string_list` `:80`, `minimal_plan_projection` `:96`,
`enrich_plan_projection` `:158`, `enrich_session_briefing_projection`
`:244`, `pack_prior_session_reviews` `:302`, `pack_transcript_turns`
`:350`, `pack_grounded_patient_messages` `:422` — all parameterized by
caller-owned `fits` predicates). The duplication is one level up: three
builders re-implement the same priority sequence (minimal plan baseline →
fits check → pack transcript/evidence → enrich plan → briefing
minimal-then-enrich → grounded messages → prior reviews) with local
`*_fits` closures and their own longitudinal-context merging:

- `therapy/context.py:115–253` (`build_untrusted_therapy_document`)
- `post_session/analysis_context.py:48–190` (`build_analysis_document`)
- `post_session/update_context.py:260–409` (`build_update_user_message`)

**Recommendation:** a small declarative "packing recipe" helper (ordered
list of `(key, producer, optional)` steps sharing one document+fits loop).
**Risk:** the highest-risk consolidation in this report —
`update_context.py` carries phase-specific invariants (frozen evidence keys
`:36–44`, evidence packed before interpretive enrichment `:266–272`) that
resist a uniform recipe; a wrong abstraction silently changes prompt
content, which is product semantics. Attempt only with the owning context
tests green before and after, and re-run the behavioral eval report.

**Validation:** `tests/unit/phases/test_context_projection.py`,
`tests/unit/phases/therapy/test_context.py`,
`tests/unit/phases/post_session/test_update_context.py` +
`test_post_session_prompts.py`; `make eval-report` when configured.

#### F15 — Data-driven merge mechanics (−85–105)

**Evidence:** `post_session/merge.py:21–41` `apply_plan_patch` is fully
mechanical (`p.x if p.x is not None else current.x` × 6);
`model_dump(exclude_none=True)` + `PlanContent.model_copy(update=...)`
collapses it to ~8 LOC. `intake/merge.py` is split: the drop rules are
**semantic and load-bearing** (source-role/sequence checks `:72–75`,
strict quote-in-message validation `:81–102`, confidence-rank conflict
resolution `:105–125`, list dedup `:128–152` — keep), but
`_merge_validated_patch` (`:223–334`, ~110 LOC) restates the `IntakeRecord`
schema field-by-field with per-leaf strategy selection and must be edited
whenever the model changes; the recursive walk it needs already exists at
`:163–202`.

**Recommendation:** collapse `apply_plan_patch` outright (low risk); convert
`_merge_validated_patch` to a declarative `(path → merge strategy + cap)`
spec walked generically (moderate risk: drop-reason diagnostics must
survive verbatim — `tests/unit/phases/intake/test_merge.py` pins them).

**Validation:** `tests/unit/phases/intake/test_merge.py`,
`tests/unit/phases/post_session/test_post_session_merge.py`; prompt-affecting
→ `make eval-report` when configured.

#### F6 — Trim config parsers where pydantic-settings already suffices (−40–70)

**Evidence:** `config.py` carries ~190 lines of `BeforeValidator` functions
and annotated types (`:51–272`). Some enforce genuine strictness beyond
library defaults (JSON-object-only fields with NaN rejection `:66–84`,
wildcard-CORS refusal `:87–115`, tight bools `:118–130`, streaming-task
structured-mode restriction `:189–222`) — keep those. The
trim-or-fail family (`_parse_non_empty_trimmed`,
`_parse_optional_non_empty_trimmed`, `_parse_log_level`, `_parse_data_dir`,
`_parse_optional_path`, `:133–186`) shares one shape and collapses into two
generic helpers.

**Recommendation:** low-priority cosmetic pass; do not weaken deliberate
strictness. Error strings are pinned by `tests/unit/test_settings.py` —
consolidate carefully. Only worthwhile when `config.py` is next touched for
a real feature.

**Validation:** `tests/unit/api/test_api_settings.py` + `tests/unit/test_settings.py`;
`make check`.

#### Micro-trims (−20–25)

- `client/console.py` retry-prompt loops in `_handle_unanswered_user`
  (`:250–280`) and `_handle_operation_stage` (`:362–378`) repeat the same
  read/validate/re-prompt pattern (~20 LOC via one helper).
- `local.py:16–18` opens a `JungApiClient` just for the health probe, then
  `run_console` opens another (~3 LOC by reusing one client).

## 5. Third-party library analysis

Evaluated against the AGENTS.md dependency policy: *add a dependency only
when it removes a meaningful Jung-owned responsibility; which Jung code
disappears?*

| Candidate | Would replace | Verdict |
|---|---|---|
| SQLAlchemy / SQLModel / ORM | `SQLiteStore` SQL + codecs | **No.** Forbidden by architecture constraints; the store's explicitness *is* the design (transaction boundaries, DDL-enforced invariants). An ORM deletes little of the 1,519 LOC — most of it is workflow-coupled mutation logic, not plumbing. |
| Instructor / pydantic-ai / LangChain / Outlines | structured-output loop | **No.** Forbidden: structured output is Jung-owned; the correction-attempt semantics (`max_retries=0`, one explicit correction) are product contracts. Wrappers add shim machinery without deleting the semantic validator. Pydantic-ai is the closest call; see Appendix A for the full evaluation and re-evaluation triggers. |
| openapi-python-client / datamodel-code-generator | DTOs + typed client | **No.** Verified: the client already imports all wire types from the shared `jung.api.contracts` module — **zero duplicated DTO definitions** (`api_client.py:22–41`). Codegen would regenerate what is already hand-shared in one module (~0 LOC saved), add a build pipeline, and lose precision like `Literal["healthy"]` (`contracts.py:239`) and frozen/`extra=forbid` configs. NDJSON streaming, request-ID correlation, and event ordering would remain hand-written anyway. |
| structlog / OpenTelemetry | diagnostics/logging | **No.** The 531 LOC own deterministic pre-disk redaction, 0600 file modes, fail-latched best-effort writes, and SQLite backup-API snapshots (`diagnostics.py:148–314`) — product safety requirements no library provides. OTel is architecturally disproportionate for a local-first tool. |
| Tenacity | retry logic | **No.** Retries are intentionally absent (fail-fast foundation rule). Verified: the client has no retry/backoff/reconnect; resilience is one transport timeout plus caller-side state re-sync (`console.py:498–500`) — proportionate for loopback, and adding retries would mask bugs against a co-located process. |
| Textual / Rich | console rendering | **No.** Rendering is fully delegated to the injected `ConsoleOutput` protocol; input already goes through `prompt_toolkit.PromptSession.prompt_async` (`terminal.py:37–39`). No markdown renderer, spinner, or ANSI machinery exists to offload — the custom parts are workflow logic (snapshot stage machine, duplicate suppression, streamed-vs-canonical reconciliation), not rendering. |
| Typer / Click | three small CLIs | **No.** argparse usage totals ~60 lines across entry points. |
| anyio / Trio adapters | asyncio runtime | **No.** Forbidden (one asyncio runtime). |
| httpx-sse / sse-starlette | NDJSON streaming | **No.** Transport is NDJSON lines over ordinary HTTP, not SSE; the hand-rolled parser is ~55 LOC including typed error mapping and per-event ID validation (`api_client.py:607–650`) — near-minimal while preserving mismatch guarantees. |
| pytest-httpx / respx | test transport | **No.** Tests deliberately use the real ASGI app / real transport; mocking at the socket layer would weaken the ownership doctrine. The 181-LOC `FakeLLM` implements the project-owned `LLMGateway` protocol with real types and real error semantics (`fake_llm.py:107–161`) — faithful, no drift-prone wire-format duplication. |

**Conclusion:** the current dependency set is right-sized. Every remaining
large module owns either therapeutic product logic or a documented safety /
contract property. Leanness gains must come from internal consolidation
(Section 4), not from adoption. The dependency-policy checklist was applied
to ten plausible candidates and none survived question 3 ("which Jung code
disappears?").

## 6. Higher-abstraction opportunities (standard library only)

Beyond the individual findings, three abstraction moves reduce code without
dependencies:

1. **Command-frame context manager** (F8) — concentrates the
   reject/lock/admission/diagnostics semantics of every mutating use case.
2. **Single owned-task await helper** (F2) — concentrates cancellation
   semantics; the highest-value concurrency abstraction in the repo.
3. **Table-driven provider-error classification** (F1) — replaces two
   exception ladders with one declarative mapping.

Deliberately **not** recommended:

- A generic "processor base class" for phases. The four processors share
  little shape (streaming vs. structured outputs differ fundamentally;
  verified shapes in §3.6); a common abstraction would be speculative
  generality.
- A generic "packing framework" beyond the modest recipe helper of F14.
  The existing `context_projection.py` primitives-with-`fits`-predicates
  design is already the right seam.
- Replacing the composition root's explicit teardown with
  `AsyncExitStack`: the manual `primary`/`cleanup_error` threading in
  `composition.py:187–360` is verbose (~70 LOC) but encodes real ordering
  guarantees (shielded aclose, cancellation drain, snapshot after
  shutdown) that an exit stack would not express more clearly.

## 7. Observations outside `src/jung`

### 7.1 Test volume and structure

| Tree | LOC | Notes |
|---|---:|---|
| `tests/unit` | 17,500 | adapters/processors/evals-CLI against FakeLLM |
| `tests/integration` | 9,499 | real `TherapyApplication` + real `SQLiteStore` via `build_test_application` |
| `tests/e2e` | 695 | real uvicorn server + real `ConsoleApp`, in-process (no subprocesses) |
| `tests/smoke` | 762 | opt-in `real_llm` local-server smoke |
| `evals/` | 7,024 | behavioral report, scenarios, simulation suite |

High volume, but justified by the ownership doctrine; the risk to watch is
higher-layer tests re-deriving lower-layer case matrices — precisely what
`tests/README.md` already forbids. Three quantified consolidation
opportunities:

1. **Integration preamble boilerplate (−250–400, low-medium risk).** The
   `fake = FakeLLM(...); async with build_test_application(store, fake)`
   preamble is hand-written ~66 times, each ending in
   `fake.assert_exhausted()`; several files also define local
   `wait_for_operation_status` variants beside the shared
   `wait_for_stage`/`wait_for_assistant_message` helpers
   (`application_fixtures.py:231–275`). A fixture pair parametrized on
   expectations, with the exhaustion assert in fixture teardown, collapses
   this. Risk: implicit fixture lifetimes must not obscure when
   `assert_exhausted()` fires.
2. **Hand-rolled near-duplicate test bodies in the two biggest unit files
   (−600–900, medium risk).** `test_openai_adapter.py` (2,311 LOC / 50
   tests) and `test_audit_and_cli.py` (2,254 LOC / 49 tests) dominate unit
   LOC with almost no parametrization (2 decorators in the audit file).
   Table-driven consolidation is real but must keep transport error-path
   cases (retries, truncation, malformed streams) explicit so a failure
   names its branch.
3. **Real-model env parsing split (−60–100, low risk).** Timeout/extra-body
   parsing exists twice — `tests/smoke/smoke_env.py` and
   `evals/harness.py:57–92` — over the same `LOCAL_LLM_SMOKE_*` namespace;
   `tests/support/local_llm.py` is the documented shared home.

Hygiene: `pytest.ini:20–21` declares `slow` and `skip` markers with zero
usages (verified by grep across `tests/` and `evals/`) — remove. The
Makefile layering (`check` deterministic gate vs. opt-in live-model
targets) is clean; `test-unit`/`test-integration` are thin subsets kept for
convenience and referenced in `docs/development.md` — keep or drop as one
decision.

### 7.2 Evals infrastructure

The 7k-LOC evals tree is the product's behavioral quality instrument and is
correctly opt-in. Suggestion: once a phase protocol reaches its frozen
OUTCOME and its conclusions stop informing new work, move operator scripts
to a clearly-labeled archive section rather than growing parallel
protocols.

### 7.3 Accepted trade-off: per-mutation snapshot-fact derivation

Every mutating store call re-runs `load_snapshot_facts` — 4 queries
(profile, any-plan, active session, current operation;
`sqlite_store.py:1074–1100`) — via `_require_stage`. At local SQLite scale
this is microseconds; recorded here as an accepted trade-off so nobody
"optimizes" it into a cache (which would reintroduce a stale-state
projection the design deliberately avoids).

## 8. What must not change

- Message-native chat truth and request-owned streaming semantics.
- Store-owned transaction boundaries and DDL-enforced invariants (schema v7).
- Structured-output ownership, single-correction semantics, `max_retries=0`.
- Diagnostic capture being strictly best-effort and side-effect-free.
- Fixed two-role LLM routing defined in source.
- The no-migration, reset-the-database stance.
- The wire/domain DTO split (architecturally forced; only the mechanical
  mapper *bodies* are reducible, per F13).
- Client protocol strictness as fail-fast contract monitoring (F7 below).

### F7 — Client protocol strictness: keep, and document why

**Evidence:** `client/api_client.py` spends roughly 300 of its 693 lines on
defensive protocol machinery: a 12-member `ProtocolErrorKind` taxonomy
(`:105–117`), sanitized nested-validation-issue reporting, request-ID echo
verification including recursive scans for nested `ErrorEnvelope`s, an
error-code↔HTTP-status cross-check table, media-type checks, and
stream-event correlation checks.

This validates a loopback HTTP conversation between two components that
ship in the same package and version. The strictness duplicates protection
that `tests/integration/client/` and the console E2E probe already provide,
but it also converts silent contract drift into loud fail-fast errors at
runtime — consistent with the "Foundation failures" rule.

**Recommendation:** keep as is (zero effort), and record one paragraph in
`architecture.md` stating that the client is intentionally a runtime
contract monitor, so future contributors do not "simplify" it by accident.
Revisit only if the client grows new routes. (A narrowing option saving
~150–250 LOC exists but trades away fail-fast coverage the product
philosophy favors.)

## 9. Prioritized action plan

| # | Action | Type | Est. effect | Validation (per AGENTS.md matrix) |
|---|---|---|---|---|
| 1 | F5 named-access row codecs | robustness | +15 LOC, kills a bug class | focused store tests + `make check` |
| 2 | F8 command-frame context manager | dedup | −80–100 LOC | `tests/integration/application/` + `make check` |
| 3 | F1 adapter error-ladder dedup | dedup | −80–120 LOC | `tests/unit/llm/` + `make check`; `make smoke-local-llm` when a server is available |
| 4 | F3 fuse JSON validation into serialization | simplification | −50–60 LOC | focused store tests + `make check` |
| 5 | F2 unified owned-task await helper | dedup | −25–40 LOC | cancellation-focused unit/integration tests + `make check` |
| 6 | F13 API mechanical layer (errors specs, mapping helpers, lifespan, routes deps) | dedup | −110–150 LOC | `tests/unit/api/` + `tests/integration/api/` + `make check` |
| 7 | F9 tracing internals consolidation | dedup | −60–80 LOC | `tests/unit/llm/test_tracing.py` + `make check` |
| 8 | F10 strict-schema assert → test-owned | simplification | −43 LOC | `tests/unit/llm/test_structured_output.py` + `make check` |
| 9 | F11 chat context helper + terminalize merge | dedup | −50–70 LOC | chat stream/cancellation tests + `make check` |
| 10 | F12 operations symmetry + ownership field | dedup | −25–40 LOC | operations/recovery tests + `make check` |
| 11 | F4 shared `UtcDateTime` | dedup | −8 LOC | `make check` |
| 12 | F7 document client strictness in `architecture.md` | docs | +1 paragraph | `make docs-links` while editing; `make check` before merge |
| 13 | F16 diagnostics write path; F17 composition resolver; micro-trims | dedup | −45–60 LOC | owning tests + `make check` |
| 14 | F6 config parser trim | cosmetic | −40–70 LOC | settings tests + `make check` (defer until `config.py` is next touched) |
| 15 | F14 packing recipe; F15 merge mechanics | consolidation | −235–355 LOC | owning phase/merge tests + `make eval-report` when configured |
| 16 | Test-suite consolidation (fixtures, table-driven adapter/audit cases, env parsing, dead markers) | tests | −900–1,400 LOC | `make check` |

Items 1–13: **≈555–750 LOC net** in production code, zero behavior change
intended, and a material reduction in duplicated
concurrency/error-handling/admission semantics. Item 14–15 are
opportunistic and touch semantic surfaces; item 16 is optional hygiene.

None of the production items require schema changes, API contract changes,
or new dependencies. F14/F15 touch prompt/merge content and must follow the
semantic-behavior validation row of the matrix.

## 10. Summary

The repository demonstrates that "lean" here is a property of disciplined
scope, not of minimal line count: strict protocol validation, cancellation
safety, and diagnostics exist because single-user software still deserves
fail-fast correctness and auditable failures. The dependency analysis
confirms the current seven-dependency stack is optimal under the project's
own policy — ten plausible candidates, none of which deletes more Jung code
than it adds. The concrete recommendations above consolidate duplicated
machinery (five command scaffolds, two exception ladders, three
shield-and-drain sites, three packing orchestrations), harden the
persistence codec boundary, and document two deliberate trade-offs —
keeping the codebase lean without touching a single product guarantee.

## Appendix A — pydantic-ai detailed evaluation

This appendix records the full reasoning behind the rejection of
[pydantic-ai](https://ai.pydantic.dev) so that a future redesign can start
from this analysis instead of repeating it. Pydantic-ai is the strongest of
the ten candidates evaluated in Section 5: it is Pydantic-native, actively
maintained, and its core feature — typed structured outputs with validation
and retry — targets exactly what `jung.llm.structured` and
`generate_structured` already do.

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

1. **The gateway protocol itself.** Architecture requires that provider
   types never leak into domain, application, phase, API, or client code.
   The project-owned `LLMGateway` protocol (`stream_text` /
   `generate_structured`) must remain the anti-leak boundary, with a new
   wrapper adapting pydantic-ai agents and message types to it — new shim
   code replacing deleted code.
2. **Diagnostics evidence capture (~300 LOC of the adapter).** Jung records
   `llm.provider.request/response/error` events with redaction,
   provider-attempt correlation IDs, latency, token usage, and correction
   triggers into its schema-v5 DiagnosticRecorder. Pydantic-ai's
   instrumentation is oriented at OpenTelemetry/Logfire. Mapping its hooks
   onto Jung's event vocabulary remains Jung-owned code of comparable size
   to what was deleted.
3. **The error taxonomy.** Jung classifies transport failures into
   `LLMUnavailable` / `LLMTimeout` / `LLMProtocolError` / `InvalidLLMOutput`,
   which drive public error codes and retryability decisions on durable
   operations. Translating pydantic-ai's exception set is another
   adaptation layer.
4. **Policy and role routing.** `ModelPolicy`, task overrides, and the
   source-defined SESSION/SUPERVISOR role split are Jung-owned by design
   and unaffected.

Net effect on LOC: close to a wash — plausibly −400 gross, +250–350 of
wrapper, instrumentation, and translation code.

### A.3 Decisive conflicts

**Physical-attempt semantics.** AGENTS.md states: "Do not enable a hidden
provider, wrapper, or SDK retry layer that changes physical-attempt
semantics." Jung's contract is `max_retries=0` on the SDK client
(`openai_compatible.py:152`), exactly one explicit correction attempt on
invalid output (`:540–620`), and provider transport failures that never
trigger validation correction. Pydantic-ai's core loop ships its own
configurable retry machinery (model retries, output retries). Preserving
Jung's exact attempt accounting would require auditing every framework
default and pinning them with tests — and even then the semantics live in
framework source, not in Jung's repository. The property "one correction,
transport failures propagate" is currently ~50 legible lines in
`generate_structured`; under pydantic-ai it becomes a configuration claim
about an external system. This alone approaches disqualification.

**Agent-framework exclusion.** The architecture explicitly excludes agent
frameworks and tool calling as application assumptions. Jung would consume
only pydantic-ai's structured-output slice, but adoption imports the
agent/tool/dependency-injection abstraction wholesale — concepts with no
Jung use case, plus a fast-moving dependency surface to track across
upgrades.

### A.4 The steelman, and why it still loses

Structured-output handling across OpenAI-compatible servers is genuinely
fiddly: providers that ignore `response_format`, reasoning models that wrap
JSON in fences, prompt-mode instruction drift. Pydantic-ai hardens exactly
these edges, and outsourcing that maintenance has real value. Three factors
blunt it here:

- Jung's edge-case surface is small and already pinned by deterministic
  tests (`tests/unit/llm/test_structured_output.py`,
  `tests/unit/llm/test_openai_adapter.py`). The scenarios are stable
  because the provider contract is fixed: Chat Completions, three
  structured modes, no tools, no streaming-structured output.
- The hard evals assert model invariants such as exact-value instruction
  resistance through Jung's correction loop. The loop's behavior is part of
  the evaluated product surface, not incidental plumbing; moving it into a
  library changes what that evidence measures.
- Strictness asymmetry: pydantic-ai optimizes for obtaining valid output
  with minimal fuss; Jung optimizes for accounting every physical attempt
  and recording evidence. These goals pull in different directions.

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
(`max_retries=0`, one explicit correction, transport failures propagate)
and must be recorded first as a change to the canonical
safety/architecture contracts, per the project's product-decision rules.
