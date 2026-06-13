# Workflow Probe Plans — Repository Review and Improved Plan

**Repository reviewed:** `HagbardCel/llm_psychology`, default branch `main`, current indexed commit `a72a30c116980f674421138b571aa796d08f5ed3`  
**Plans reviewed:**

- `workflow_probe_assessment_mitigation_plan.md`
- `workflow_probe_fix_plan.md`

**Requested prioritization:** medical-safety items are intentionally de-prioritized for this stage. They are kept as backlog items, not ignored.

---

## 1. Executive conclusion

Both plans are directionally useful, but they are partly stale against the current repository. Several fixes proposed in `workflow_probe_fix_plan.md` appear already implemented on `main`: `DEFAULT_CONCRETE_STEP_TERMS` already includes `"breath"`, intake streaming already receives `phase="intake_response"`, and the cited structured-output call sites already pass a non-null phase. The strict `timing_no_unphased_llm_calls == 0` assertion remains correct, but the proposed edits are no longer the right patch.

The assessment mitigation plan is more valuable as a quality roadmap, but it mixes current gaps with already-solved items and with a few over-broad or over-invasive prescriptions. The highest-value near-term work is not medical triage. It is:

1. **Normalize phase taxonomy and timing instrumentation** so probe timings explain actual user-visible latency.
2. **Unify or share intake slot evidence logic** between backend and probe recorder, then tighten duration detection without rejecting valid coarse duration statements.
3. **Add probe-quality metrics for intake behavior and user-simulator realism.**
4. **Make assessment recommendations and profile updates evidence-aware without a large schema rewrite first.**
5. **Make workflow actions WebSocket-first and idempotent at the execution layer, not just deduplicated in recorder artifacts.**

---

## 2. Review of `workflow_probe_fix_plan.md`

### 2.1 Correct claims

| Claim | Verdict | Notes |
|---|---:|---|
| The concrete-step assertion is lexical/sub-string based. | Correct | `therapy_response_has_concrete_next_step` checks whether one of the configured concrete-step terms appears in the first therapy response. |
| `timing_no_unphased_llm_calls` is a valid strictness check. | Correct | The recorder calculates `llm_unphased_finish_count`; assertions expect zero. Keeping this strict is useful because phase coverage is the contract for probe interpretability. |
| Intake responses need a separate phase from therapy responses. | Correct conceptually | This is already implemented in the current repo. |
| Every structured LLM pathway should carry an explicit phase. | Correct conceptually | This is also already mostly implemented, but current phase names are still too coarse. |

### 2.2 Incorrect or stale claims

| Plan claim | Current repo reality | Correction |
|---|---|---|
| Add `"breath"` to `DEFAULT_CONCRETE_STEP_TERMS`. | Already present in `console-ui/src/workflow_probe/assertions.py`. | Do not patch this again. Add a regression test instead. |
| `trio_conversation_manager.py` has `phase=None` for all non-therapist agents. | Current code already maps `agent == "INTAKE"` to `"intake_response"`. | Treat this as fixed; add test coverage. |
| Four structured-output call sites pass `phase=None`. | Current code passes non-null phases: intake extraction uses `assessment_generation`; session enrichment and memory use `post_session_update`; deep-topic detection uses `therapy_response`. | The remaining improvement is semantic phase precision, not unphased-call elimination. |
| “No new tests needed.” | Wrong. | Add tests precisely because the repository has already drifted from the plan. The probe is too slow and too end-to-end to be the only guard. |

### 2.3 Better replacement for this plan

Replace the old fix plan with this smaller patch set:

1. Add tests that assert:
   - `DEFAULT_CONCRETE_STEP_TERMS` includes both `"breathe"` and `"breath"`.
   - INTAKE streaming calls produce `phase="intake_response"`.
   - all structured-output helpers pass a non-null phase.
2. Introduce a canonical phase taxonomy, preferably as a `Literal` or enum-like constants module, and use it at call sites.
3. Split overly broad current phases:
   - `assessment_generation` currently covers style assessment, Tier 1 extraction, and Tier 3 initial formulation.
   - `post_session_update` currently covers several distinct jobs.
   - `therapy_response` currently also covers deep-topic detection.
4. Keep `timing_no_unphased_llm_calls` strict.

---

## 3. Review of `workflow_probe_assessment_mitigation_plan.md`

### 3.1 P0-1 — Evidence-backed intake slot coverage

**What is correct**

- The backend already has evidence-bearing slot details (`SlotEvidence`) and `identify_required_slots()` filters hard slots by explicit patient evidence.
- The `duration` matcher still contains a broad `since ...` regex that can create false positives.
- The probe recorder contains a standalone slot-evidence replica, which is a maintainability risk.

**What is incorrect or needs refinement**

- The plan says to “ensure `slot_evidence` is always included” in backend diagnostics and recorder diagnostics. In the current repo, `intake_completion_diagnostics()` already returns `slot_evidence`, and the recorder’s `_intake_completion_diagnostics()` also emits `slot_evidence`.
- The plan treats “since I was a kid” as a duration false positive. That is not obviously wrong evidence. Clinically and logically, it is a valid coarse onset/duration statement. The false-positive problem is broader: `since` matches arbitrary clauses such as “since I was asked to present,” which may not indicate duration.
- A minimum quote length is not a robust fix. “For two days” is a valid duration statement and could be short. Validation should apply to the matched expression, not to the total evidence quote.

**Better fix**

- Replace the broad `since` regex with explicit duration/onset classes:
  - precise calendar onset: `since March`, `since 2024`, `since last summer`
  - coarse developmental onset: `since childhood`, `since I was a kid`, `since I was 12`
  - rolling duration: `for three months`, `over several weeks`, `past few days`
  - frequency: `daily`, `nightly`, `twice a week`
- Add `specificity` or `evidence_kind` to duration evidence: `precise_duration`, `coarse_onset`, `frequency`, `ambiguous`.
- Replace recorder duplication with a shared implementation or explicit parity tests.
- Align recorder and backend `risk_screen` keyword handling; currently the backend accepts `urgent`, `medical`, and `chest`, while the recorder replica only accepts self-harm/safety-style keywords.

---

### 3.2 P0-2 — Medical triage

**Verdict:** logically correct but de-prioritized.

The current intake prompt directly asks about self-harm and whether chest tightness feels medically urgent. The therapist prompt has a medical-boundary guideline. The intake agent does not implement a separate red-flag micro-flow; it only routes required follow-ups such as risk screen, goal preference, and coping attempts.

For this stage, keep this as **Backlog P3**. Do not let it displace timing, phase, probe, and evidence-grounding improvements.

---

### 3.3 P0-3 — User-visible latency instrumentation

**What is correct**

- The current metrics do not fully explain user-visible latency.
- The recorder already computes user-visible response latency from `user_input`, WebSocket chunks, and `assistant_response`, but this is not yet reconciled with backend LLM phase timing.
- LLM metrics include `latency_ms`, `provider_latency_ms`, `total_wall_ms`, `ttft_ms`, and `stream_ms`, but do not explicitly report `prompt_eval_ms`, request-boundary timing, post-stream persistence, or endpoint blocking time.

**What is incomplete in the plan**

- The plan says to timestamp around `self.llm.stream(messages)`, but the request boundary is subtle because the iterator executes inside a thread. The implementation should track when the stream iterator actually starts pulling chunks.
- The plan does not define how to correlate user-visible samples with backend call IDs/phases. Without correlation, undercoverage warnings remain approximate.

**Better fix**

- Add `call_id` to WebSocket metadata or probe-only diagnostic events when feasible.
- In `stream_response()`, log:
  - `lifecycle_ms`: from API/request entry to completion
  - `rate_limit_wait_ms`
  - `request_boundary_ms`: time inside the provider call boundary
  - `prompt_eval_ms`: first chunk minus request boundary start
  - `generation_ms`: finish minus first chunk
  - `chunk_count` and emitted character count
- In conversation/orchestration layer, separately log:
  - prompt construction time
  - RAG augmentation time
  - LLM streaming time
  - DB persistence time after stream completion
  - WebSocket dispatch completion time
- In recorder, compute:
  - user-visible latency by session type
  - backend-timed latency by phase
  - undercoverage ratio: `user_visible_ms / matched_backend_total_ms`
  - warning when ratio exceeds threshold, but avoid failing the whole probe unless thresholds are scenario-defined.

---

### 3.4 P0-4 — Intake leadingness and progress inflation

**What is correct**

- The intake continuation prompt lacks explicit response-shape constraints such as word count, number of questions, repeated opener avoidance, and limits on interpretive/leading language.
- There is no output validation/filtering after the intake LLM response.

**What should be improved**

- Do not start with hard output filtering. First improve prompt constraints and add probe metrics. Use hard blocking only for severe leakage or role violations.
- Add measurable assertions before relying on subjective transcript review:
  - average intake response length
  - max intake response length
  - repeated opener count
  - banned progress-claim count
  - question count per turn
  - leading-question pattern count
  - topic stagnation count, e.g. 3+ consecutive assistant turns on same slot without progress

**Proposed prompt additions**

Add to `CONTINUE_CONVERSATION_PROMPT`:

```text
Conversation constraints:
- Ask at most one primary question and one brief clarifying question.
- Keep the response under 120 words unless safety requires more.
- Do not announce progress, breakthroughs, healing, transformation, or insight.
- Do not interpret the patient's motives before asking for their own framing.
- Do not repeat the same opener in consecutive turns.
- If two turns have not advanced a required slot, ask the next missing required slot directly.
```

---

### 3.5 P0-5 — User simulator hardening

**What is correct**

- The simulator system prompt is minimal.
- The scenario persona is cooperative and reflective, which can mask leadingness and inflate therapeutic quality.
- The simulator prompt does not explicitly resist mirroring therapist language.

**What should be improved**

- Keep deterministic replies as the default smoke-test baseline.
- Add a separate LLM-user-sim scenario suite for realism and robustness; do not destabilize the core smoke test first.
- Add simulator-output diagnostics rather than only prompt changes:
  - n-gram overlap with immediately preceding therapist message
  - therapist-introduced term adoption rate
  - sudden-improvement/progress language in simulated user turns
  - persona drift markers

---

### 3.6 P1-1 — Profile provenance

**What is correct**

- `UserProfile` stores interpretive fields such as `family_atmosphere`, `relationship_to_work`, `social_context`, and `current_situation` as plain strings.
- The extraction prompt says to extract only explicit patient statements, but the schema does not structurally enforce provenance.

**What is too invasive**

- Replacing many `UserProfile` fields with a `ProfileField` wrapper is a large schema/API migration.
- The current repo uses a single “current schema” declaration and rejects old legacy DBs rather than maintaining a chain of numbered migrations. A proposed migration plan should reflect that project style.

**Better fix**

Start with a lightweight provenance layer:

- Keep `UserProfile` fields as backwards-compatible strings.
- Add either:
  - `user_profile_field_evidence` table, or
  - JSON column `profile_evidence` keyed by field name.
- For each extracted field, store:
  - `value`
  - `source`: `patient_stated`, `llm_summary`, `therapist_note`, `clinical_inference`
  - `evidence_session_id`
  - `evidence_message_index`
  - `evidence_quote`
  - `confidence`
  - `created_at`
- Update merge logic to preserve existing field values unless new evidence is stronger or more recent.

---

### 3.7 P1-2 — Evidence spans for assessment recommendations

**What is correct**

- `StyleAssessmentOutput` currently contains only `assessment`, `score`, and `key_topics`.
- Downstream `TherapyStyleRecommendation` and recommendation metadata only expose style, score, explanation, and topics.
- The prompt asks for evidence-based recommendations but does not require quotes or mismatch reasons.

**What the plan misses**

Adding fields only to `StyleAssessmentOutput` is insufficient. The extra evidence will be dropped unless downstream models, persistence, and serialization are updated.

**Better fix**

- Add structured evidence fields to `StyleAssessmentOutput`.
- Add equivalent fields to `TherapyStyleRecommendation` or preserve the raw style-assessment payload in recommendation metadata.
- Persist evidence in `assessment_recommendations`.
- Update `format_recommendations()` to show concise user-friendly evidence, not raw clinical internals.
- Add validators:
  - every positive fit reason needs a quote or `evidence_strength != none`
  - unsupported style-specific claims are rejected or downgraded
  - scores above `0.90` require at least two direct evidence spans and one mismatch/uncertainty note

---

### 3.8 P1-3 — CBT-specific response validators

**What is correct**

- The CBT prompt already contains CBT mechanisms such as thought records and behavioral experiments, but the probe does not assert that the therapist actually uses CBT methods in the first therapy interaction.

**What is too rigid**

- “Each session must include at least one explicit CBT mechanism” is too blunt. It can over-constrain therapeutic flow and encourage keyword stuffing.

**Better fix**

Use scenario-level expectations:

- For a CBT smoke scenario after work-anxiety disclosure, require one of:
  - thought-feeling-behavior chain
  - automatic thought identification
  - concrete between-session observation/tracking step
  - behavioral experiment framing
- Keep this as a probe assertion, not a universal therapist rule.

---

### 3.9 P1-4 / A2-A3 — Job status, polling, WebSocket-first behavior, and deduplication

**What is already implemented**

- A `JobStatusDTO` exists.
- `/api/jobs/<job_id>?user_id=...` exists.
- `resolve_job_status()` supports assessment, plan update, session enrichment, and aggregate post-session update job IDs.
- The probe runner already checks WebSocket job status first and falls back to HTTP polling.
- The recorder deduplicates logical workflow-action artifacts separately from raw deliveries.

**What is still missing**

- The console client still polls `_get_next_action()` in the workflow loop and only passively records WebSocket `workflow_next_action`; it does not truly process WebSocket workflow actions first.
- Execution deduplication is not the same as recorder deduplication. The recorder can suppress duplicate artifact rows while the client might still execute duplicate side-effectful actions if polling delivers the same instruction again.

**Better fix**

- Add an action execution guard keyed by `(required_action, state_signature, session_id)`.
- Apply guard only to side-effectful actions: `complete_profile`, `select_therapy_style`, `start_therapy`, `start_intake`, `continue_therapy`, `retry_plan_update`.
- Clear guard on workflow-state change or explicit retry instruction.
- Add a WebSocket-first path: if a fresh `workflow_next_action` arrives with a new state signature, process it without waiting for the next HTTP poll.
- Keep HTTP polling as fallback.

---

### 3.10 P1-5 — Briefing semantics

**What is correct**

- `Session.session_briefing` and `TherapyPlan.session_briefing` are semantically ambiguous.
- The current `Session.session_briefing` description says it is generated for the next session, while the session row also represents the completed session. This makes it unclear what the therapist used as input versus what was produced as handoff.

**Better fix**

Use explicit names:

- `Session.session_start_briefing`: briefing actually used at the beginning of this session.
- `Session.post_session_handoff`: structured output produced after this session.
- `TherapyPlan.next_session_briefing`: latest handoff to apply to the next session.

Given the current single-schema approach, update the DDL and repos directly if existing local DB reset is acceptable. Otherwise, keep compatibility aliases in DTO serialization for one transition period.

---

### 3.11 P2-1 — `patient_analysis` table status

**Plan issue**

The mitigation plan says to decide whether `patient_analysis` is unused and maybe drop it. Against the current repo, it is not simply dead schema.

**Current repo reality**

- `patient_analysis` exists in the current schema.
- Domain models define `PatientAnalysis` and `PatientAnalysisVersion`.
- Initial formulation extraction creates a Tier 3 `PatientAnalysisVersion`.
- The reflection Tier 3 pipeline reads and updates latest patient analysis.
- `TrioDatabaseService` exposes patient-analysis methods.

**Better fix**

- Keep `patient_analysis`.
- Add documentation clarifying that it is Tier 3 dynamic formulation.
- Add probe assertions only if the smoke workflow is expected to create initial Tier 3 formulation after style selection.
- Add snapshot checks for:
  - exactly one initial Tier 3 analysis after first assessment/style selection
  - version increments only after real Tier 3 updates

---

### 3.12 P2-4 — Token accounting

**What is correct**

- Current metrics rely on `usage_metadata`; for local OpenAI-compatible backends this may be absent.
- Probe artifacts should report token coverage by phase.

**Better fix**

- Add `token_count_status`: `provider_reported`, `estimated`, `missing`.
- Use provider usage when available.
- Use a cheap fallback tokenizer/estimator only for diagnostics; do not make hard budget assertions depend on approximations.
- Record counts per phase and call type.

---

## 4. Improved implementation plan

### Priority rules for this stage

Medical-safety work is moved to **Backlog P3**. The current priority is workflow-probe correctness, observability, latency explainability, and conversation-quality measurement.

| Priority | Theme | Main owner | Why now |
|---|---|---|---|
| P0 | Probe correctness and observability | Backend + harness | Without this, probe results are not trustworthy. |
| P1 | Conversation-quality measurement | Prompt + harness | Needed to prevent regressions without relying on subjective review. |
| P2 | Evidence/provenance data model | Backend | Important but slightly more invasive. |
| P3 | Medical safety flows | Backend + prompt | Important eventually, but explicitly de-prioritized for this stage. |

---

## 5. P0 plan — make the probe trustworthy

### P0-1: Remove stale fix-plan actions and add regression tests

**Actions**

1. Do not add `"breath"`; it already exists.
2. Do not add `intake_response`; it already exists.
3. Do not patch structured-output call sites merely to avoid `None`; they already have phases.
4. Add unit tests/regression tests for the already-fixed behavior.

**Suggested tests**

- `tests/unit/test_workflow_probe_assertions.py`
  - assert `"breath" in DEFAULT_CONCRETE_STEP_TERMS`
  - assert `"breathe" in DEFAULT_CONCRETE_STEP_TERMS`
- `tests/unit/test_llm_phase_contract.py`
  - monkeypatch `LLMService.stream_response()` and verify INTAKE passes `phase="intake_response"`
  - monkeypatch `generate_structured_output_async()` for extraction/enrichment/memory/deep-topic helpers and assert non-null phase

---

### P0-2: Define a canonical LLM phase taxonomy

**Problem**

Current phase coverage is mostly non-null, but phases are semantically overloaded.

**Recommended phases**

```python
LLMPhase = Literal[
    "intake_response",
    "intake_extraction",
    "assessment_style_scoring",
    "assessment_initial_formulation",
    "initial_plan_generation",
    "therapy_opening",
    "therapy_response",
    "therapy_deep_topic_detection",
    "session_enrichment",
    "memory_analysis",
    "plan_reflection",
    "tier3_change_detection",
    "tier3_update",
]
```

**Concrete remapping**

| Current call site | Current phase | Proposed phase |
|---|---|---|
| Intake streaming | `intake_response` | keep |
| Tier 1 extraction | `assessment_generation` | `intake_extraction` |
| Style scoring | `assessment_generation` | `assessment_style_scoring` |
| Tier 3 initial formulation | `assessment_generation` | `assessment_initial_formulation` |
| Tier 4 initial plan | `initial_plan_generation` | keep |
| Deep-topic detection | `therapy_response` | `therapy_deep_topic_detection` |
| Session enrichment | `post_session_update` | `session_enrichment` |
| Memory session analysis | `post_session_update` | `memory_analysis` |
| Tier 3 change detection/update | `post_session_update` | `tier3_change_detection` / `tier3_update` |

**Acceptance criteria**

- `timing_no_unphased_llm_calls` remains strict.
- Timing summary includes the new phase names.
- Existing scenario timing thresholds are updated to use the new phase names or grouped in a derived summary.

---

### P0-3: Improve LLM and user-visible latency instrumentation

**Actions**

1. Extend `LLMService._log_metric()` with optional:
   - `request_boundary_ms`
   - `prompt_eval_ms`
   - `generation_ms`
   - `chunk_count`
   - `completion_chars`
   - `token_count_status`
2. In `stream_response()`:
   - track rate-limit wait separately
   - track first chunk from the point the provider iterator starts
   - track generation duration after first chunk
3. In `trio_conversation_manager.py`:
   - time RAG retrieval separately
   - time prompt/context construction separately
   - time DB persistence after streaming separately
4. In recorder:
   - compute undercoverage ratio between user-visible latency and backend-phase timing
   - emit warning instead of immediate failure unless threshold configured

**Acceptance criteria**

- For every assistant response sample, probe artifacts can explain at least 80% of user-visible latency via one or more backend/probe timing buckets, or emit a clear undercoverage warning.
- `summary.md` includes both backend phase timing and user-visible latency.

---

### P0-4: Unify intake slot evidence between backend and probe

**Actions**

1. Move shared slot detection into an importable module used by both backend and recorder, or add a strict parity test that runs backend and recorder logic over the same synthetic transcript.
2. Replace broad `since` duration pattern with explicit onset/duration classes.
3. Add a duration `evidence_kind` field.
4. Align recorder risk-screen logic with backend risk-screen answer keywords.

**Test matrix**

Should cover duration:

- `"for three months"` → covered, precise duration
- `"over several weeks"` → covered, approximate duration
- `"past few days"` → covered, rolling duration
- `"daily"` → covered, frequency
- `"since childhood"` → covered, coarse onset
- `"since I was a kid"` → covered, coarse onset
- `"since I was asked to present"` → missing or ambiguous, not covered as duration
- `"it is happening now"` → missing

Should cover risk-screen parity:

- direct self-harm denial → covered
- `"not medically urgent"` after risk prompt → covered
- `"it feels medically urgent sometimes"` after risk prompt → covered for risk-screen slot, but medical triage remains backlog

---

### P0-5: Make workflow action execution idempotent and WebSocket-first

**Actions**

1. Add `self.executed_action_signatures: set[str]` to console client.
2. Before executing side-effectful actions, compute key:
   ```python
   key = f"{action}:{session_id}:{state_signature}"
   ```
3. Skip duplicate execution if key already executed and workflow state has not changed.
4. Use WebSocket `workflow_next_action` as the preferred next action when its state signature differs from the last processed action.
5. Keep HTTP polling fallback.

**Acceptance criteria**

- Raw workflow action deliveries can be duplicate.
- Logical workflow actions should be deduplicated in recorder.
- Side-effectful client executions must happen once per state signature.

---

## 6. P1 plan — measure and improve conversation quality

### P1-1: Add intake quality assertions

**Actions**

Add recorder/assertion metrics:

- `intake_response_avg_words`
- `intake_response_max_words`
- `intake_question_count_max`
- `intake_repeated_opener_count`
- `intake_progress_language_count`
- `intake_leading_question_count`
- `intake_topic_stagnation_count`

**Banned or suspicious language list**

- `breakthrough`
- `transformation`
- `healing journey`
- `profound shift`
- `you made progress`
- `we have already uncovered`

**Acceptance criteria**

- Core smoke scenario should not fail solely on subjective style, but should warn on quality issues.
- Dedicated conversation-quality scenario can fail on these metrics.

---

### P1-2: Update intake prompt constraints

Add concise constraints to `CONTINUE_CONVERSATION_PROMPT`. Keep them testable and minimal.

**Acceptance criteria**

- Unit test verifies prompt contains word-limit, question-limit, and no-progress-claim constraints.
- Probe metrics improve without reducing intake completion reliability.

---

### P1-3: Harden LLM user simulator in separate scenarios

**Actions**

- Add anti-mirroring instructions.
- Add persona-stability block.
- Add persona variants:
  - cooperative baseline
  - guarded baseline
  - avoidant user
  - contradiction/low-detail user
  - style tie case
- Add simulator diagnostics:
  - n-gram overlap
  - therapist-term adoption
  - sudden symptom improvement
  - persona drift

**Acceptance criteria**

- Deterministic smoke remains stable.
- LLM-user-sim scenarios become diagnostic, not the only pass/fail gate.

---

### P1-4: Style-specific response assertions without keyword stuffing

**Actions**

For CBT scenario, require a first therapy response that includes at least one of:

- automatic thought identification
- thought-feeling-behavior chain
- tracking/writing task
- behavioral experiment framing
- grounding/breathing step tied to anxiety activation

Use phrase patterns rather than a single fixed keyword list.

**Acceptance criteria**

- A natural CBT response passes.
- A generic supportive response without CBT mechanism warns or fails depending on scenario.

---

## 7. P2 plan — evidence and schema improvements

### P2-1: Add evidence-backed assessment recommendations

**Actions**

1. Add evidence models to `StyleAssessmentOutput`.
2. Preserve evidence downstream in `TherapyStyleRecommendation` or metadata.
3. Persist evidence with assessment recommendations.
4. Add validation and score calibration.
5. Render concise evidence to users while keeping raw evidence in artifacts.

**Acceptance criteria**

- Every recommendation has at least one direct evidence quote.
- Every high score has a direct quote and an uncertainty/mismatch note.
- Unsupported claims such as dreams, slips, transference, archetypes, or childhood trauma are absent unless present in transcript.

---

### P2-2: Add lightweight profile provenance

**Actions**

- Add `profile_evidence` JSON or a normalized `user_profile_field_evidence` table.
- Do not replace all `UserProfile` fields with wrappers in the first iteration.
- Update merge logic to preserve evidence and avoid overwriting patient-stated fields with lower-confidence summaries.

**Acceptance criteria**

- Existing DTOs remain backward compatible.
- Probe artifacts show evidence source for extracted Tier 1 fields.

---

### P2-3: Clarify briefing semantics

**Actions**

Rename or alias:

- `Session.session_start_briefing`
- `Session.post_session_handoff`
- `TherapyPlan.next_session_briefing`

**Acceptance criteria**

- A completed session stores what was used at start and what was generated after completion separately.
- The therapist reads only the correct start briefing.
- Probe asserts the briefing used for therapy session startup is persisted.

---

### P2-4: Keep and document `patient_analysis`

**Actions**

- Do not drop `patient_analysis`.
- Document it as Tier 3 dynamic formulation.
- Add probe assertion only if the current smoke flow is supposed to create initial formulation.

**Acceptance criteria**

- First style selection creates expected Tier 3 formulation, or docs explicitly state why this is deferred.
- Post-session Tier 3 updates are versioned and lineage is clear.

---

## 8. P3 backlog — medical-safety items

These are not priority for the current implementation stage, per instruction.

**Backlog actions**

- Add medical red-flag detection separate from risk-screen slot completion.
- Add a direct triage follow-up when a patient reports possibly urgent chest symptoms.
- Add escalation wording when symptoms are new, severe, worsening, radiating, associated with fainting, severe shortness of breath, etc.
- Add a dedicated medical triage scenario later.

**Important distinction**

Risk-screen slot completion should mean: “the application asked and the patient answered the safety/urgency screen.” It should not mean: “all medical risk has been handled.” Those are different state concepts.

---

## 9. Suggested implementation order

| Phase | Work | Rationale |
|---|---|---|
| 1 | Remove stale fix-plan changes; add regression tests for `breath`, `intake_response`, and non-null phases | Prevent redundant patches and lock in current fixes. |
| 2 | Phase taxonomy + timing instrumentation | Makes probe artifacts interpretable. |
| 3 | Shared/parity-tested intake slot evidence; duration regex fix | Prevents false intake completion and recorder/backend drift. |
| 4 | Workflow action idempotency + WebSocket-first client behavior | Removes duplicated action ambiguity and polling overhead. |
| 5 | Intake prompt constraints + quality assertions | Improves conversation quality measurably. |
| 6 | User simulator variants and diagnostics | Makes realism failures observable without destabilizing smoke test. |
| 7 | Assessment evidence spans and profile provenance | Higher-value clinical/data quality work, but more schema impact. |
| 8 | Briefing renames and patient-analysis docs/assertions | Semantic cleanup after observability is stable. |
| 9 | Medical triage backlog | Re-prioritize once core workflow probe is reliable. |

---

## 10. Summary of corrections to the attached plans

| Attached plan item | Keep / change / drop | Reason |
|---|---|---|
| Add `"breath"` to concrete-step terms | Drop | Already implemented. Add test instead. |
| Add `intake_response` phase | Drop | Already implemented. Add test instead. |
| Add non-null phase to cited structured-output calls | Change | Already non-null; improve semantic phase names instead. |
| No tests needed | Drop | Tests are needed because the plan is already stale. |
| Tighten duration regex | Keep, but change approach | Do not reject “since I was a kid”; classify coarse onset. |
| Emit backend and recorder `slot_evidence` | Drop as implementation task | Already present. Add parity tests and align risk keywords. |
| Medical red-flag micro-flow | Move to P3 backlog | Requested de-prioritization. |
| User-visible latency instrumentation | Keep and expand | Add correlation and timing buckets beyond LLM call time. |
| Intake prompt constraints | Keep | Good low-cost improvement. |
| User simulator anti-mirroring | Keep, but isolate | Use separate LLM-sim scenarios rather than destabilizing smoke. |
| Profile provenance via `ProfileField` wrappers | Change | Start with lightweight evidence table/JSON. |
| Assessment evidence spans | Keep and expand downstream | Must preserve fields through recommendation DTO/storage. |
| CBT mechanism assertion | Change | Make scenario-specific, not universal. |
| Job status events / endpoint | Mostly already implemented | Focus on WS-first execution and idempotency. |
| `patient_analysis` maybe unused | Drop | It is used for Tier 3 formulation/versioning. Document and assert instead. |
| Token accounting fallback | Keep | Add provider/estimated/missing status. |

