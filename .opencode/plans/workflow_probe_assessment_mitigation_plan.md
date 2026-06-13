# Workflow Probe Assessment — Mitigation Plan

**Assessment ref:** `docs/reference/workflow_probe_assessment_20260612.md`
**Date:** 2026-06-13
**Status:** Draft — awaiting review

---

## Executive summary

The assessment identified 17 issues across three axes: evidence-grounded state, user-visible performance, and conversation realism. This plan maps each issue to its root code location, describes the gap, and specifies the concrete code changes required. Issues are organized by the assessment's priority levels (P0, P1, P2).

---

## P0 — Fix before treating the workflow as robust

### P0-1: Evidence-backed intake slot coverage (A4)

**Severity:** High
**Assessment ref:** A4 (lines 253-299)

#### Root code
- `src/psychoanalyst_app/agents/intake/slots.py` — slot detection, `SlotEvidence` TypedDict, `identify_required_slots()`, `intake_completion_diagnostics()`
- `console-ui/src/workflow_probe/recorder.py` — standalone slot detection replica in `_intake_slot_evidence_from_transcript()`

#### Gap analysis
The backend's `identify_required_slots()` (line 267-282) already enforces evidence-backed filtering for hard slots: it requires `explicitness == "explicit"`, `evidence_role == "user"`, and a non-empty `evidence_quote`. However, the `duration` slot has regex patterns that produce false positives — e.g., phrases like "now" or "as a kid" loosely trigger the `since` pattern. The probe's `covered_slots` output in the recorder is a sorted list of slot names, losing the per-slot evidence details.

#### Changes
1. **`src/psychoanalyst_app/agents/intake/slots.py`** — tighten duration regex:
   - Replace broad `since` pattern with more specific patterns requiring a duration quantity (e.g., "since March 2026" not "since I was a kid").
   - Add a minimum evidence-quote length for the `duration` slot (e.g., ≥ 20 characters) to reject trivial matches.

2. **`src/psychoanalyst_app/agents/intake/slots.py`** — ensure `slot_evidence` is always included in `intake_completion_diagnostics()` output.

3. **`console-ui/src/workflow_probe/recorder.py`** — in `_intake_completion_diagnostics()`, emit `slot_evidence` alongside `covered_slots` so the probe artifact contains per-slot evidence spans.

4. **`tests/unit/test_trio_intake_agent.py`** — add test: vague phrases like "it's been happening now" or "since I was a kid" must NOT cover the `duration` slot.

---

### P0-2: Medical-triage handling for urgent chest tightness (A5)

**Severity:** High
**Assessment ref:** A5 (lines 301-334)

#### Root code
- `src/psychoanalyst_app/agents/intake/slots.py` — `RISK_SCREEN_PROMPT` (line 34-37), risk_screen detection (line 298-313)
- `src/psychoanalyst_app/agents/intake/agent.py` — `process_message()`, follow-up logic (line 203-214)
- `src/psychoanalyst_app/agents/therapist/prompts.py` — medical boundary guideline #10 (line 61)

#### Gap analysis
The `RISK_SCREEN_PROMPT` asks about self-harm and physical symptom urgency. The therapist's continuation prompt has a medical boundary rule. However, when the patient says chest tightness "feels urgent sometimes," the intake agent does not trigger a **medical red-flag micro-flow**. It moves directly into psychological formulation. The risk_screen slot is satisfied by the keyword "urgent" appearing in the answer, but no follow-up questions about medical evaluation, red flags, or escalation guidance are generated.

#### Changes
1. **`src/psychoanalyst_app/agents/intake/slots.py`** — add keyword detection for medical red flags: "chest pain", "chest tightness", "fainting", "shortness of breath", "radiating", "medically urgent". When these appear in a patient message, set a `medical_red_flag` flag.

2. **`src/psychoanalyst_app/agents/intake/prompts.py`** — add a `MEDICAL_TRIAGE_PROMPT` with red-flag questions:
   - Is this new, severe, worsening, or unlike previous anxiety symptoms?
   - Any shortness of breath, fainting, radiating pain, sweating, nausea, or cardiac history?
   - Has a medical professional evaluated it?

3. **`src/psychoanalyst_app/agents/intake/agent.py`** — in `process_message()`, after slot detection, check for `medical_red_flag`. If set, emit the medical triage prompt as a direct follow-up (bypassing LLM), similar to how `risk_screen` is handled.

4. **`src/psychoanalyst_app/agents/intake/prompts.py`** — add an `MEDICAL_ESCALATION_PROMPT` for cases where the patient confirms acute/severe/new symptoms: advise seeking urgent medical care.

5. **`tests/unit/test_trio_intake_agent.py`** — add test: "chest tightness feels urgent" triggers medical triage follow-up before intake completes.

---

### P0-3: User-visible latency instrumentation (A1)

**Severity:** High
**Assessment ref:** A1 (lines 86-166)

#### Root code
- `src/psychoanalyst_app/services/llm_service.py` — `_log_metric()` (line 361-416), `stream_response()` (line 569-662), `generate_response()` (line 425-553)
- `console-ui/src/workflow_probe/recorder.py` — `_load_llm_timing_summary()` (line 292-335), user-visible latency computation (line 368-443)

#### Gap analysis
`backend_llm_calls.jsonl` captures `latency_ms`, `total_wall_ms`, `ttft_ms` (streaming only), and `stream_ms`. Missing: prompt evaluation/prefill time on the LLM server, socket/stream setup time, parse time, persistence time, and API endpoint blocking time. The first therapy response shows 57.1s user-visible latency vs 2.0s logged `therapy_response_ms` — a ~55s gap attributed to unmeasured components (primarily prompt evaluation on the local model server).

#### Changes
1. **`src/psychoanalyst_app/services/llm_service.py`** — in `stream_response()`, add timestamps around the LangChain call boundary:
   - `request_started_at`: before `self.llm.stream(messages)` is invoked
   - `request_done_at`: after the iterator completes
   - Emit `prompt_eval_ms = first_chunk_at - request_started_at` and `generation_ms = finished_at - first_chunk_at`

2. **`src/psychoanalyst_app/services/llm_service.py`** — in `_log_metric()`, add fields: `prompt_eval_ms`, `generation_ms`, `request_boundary_ms`.

3. **`src/psychoanalyst_app/orchestration/trio_conversation_manager.py`** — wrap the LLM call + WebSocket dispatch in a timing scope. Record `endpoint_start_at` and `endpoint_done_at`. Emit an `endpoint_latency` metric.

4. **`console-ui/src/workflow_probe/recorder.py`** — in `_load_llm_timing_summary()`, compute `prompt_eval_total`, `generation_total`, `endpoint_latency` per phase.

5. **`console-ui/src/workflow_probe/recorder.py`** — add `llm_latency_undercoverage` warning when transcript user→assistant delay >> logged LLM latency (threshold: ratio > 3x).

6. **`tests/unit/test_llm_service.py`** — add test: streaming metrics include `prompt_eval_ms` and `generation_ms` fields.

---

### P0-4: Intake leadingness and progress inflation (B1, B2, B3)

**Severity:** Medium-high (B1), High (B2), Medium-high (B3)
**Assessment ref:** B1 (lines 470-504), B2 (lines 508-544), B3 (lines 546-575)

#### Root code
- `src/psychoanalyst_app/agents/intake/prompts.py` — `CONTINUE_CONVERSATION_PROMPT` (line 24-43): no verbosity or style constraints
- `src/psychoanalyst_app/agents/intake/agent.py` — `process_message()` — no output filtering

#### Gap analysis
The intake prompt has no constraints on: verbosity (therapist has 90-160 word limit, intake has none), questions per turn, repeated openers ("thank you for sharing"), leading/implanted interpretations, progress/breakthrough language, or topic progression. The intake loops on somatic symptoms without slot advancement.

#### Changes
1. **`src/psychoanalyst_app/agents/intake/prompts.py`** — add constraints to `CONTINUE_CONVERSATION_PROMPT`:
   ```
   Conversation constraints for intake:
   - Ask at most 1-2 questions per turn.
   - Keep responses under 120 words unless safety requires more.
   - Do not include process meta-commentary such as "this helps us understand..." or "we have X minutes left."
   - Do not offer an interpretation before eliciting the patient's own framing.
   - Do not ask questions whose answer is embedded in the question.
   - Avoid progress claims such as "breakthrough," "healing," "transformation," "critical breakthrough," "profound shift."
   - After two consecutive turns on the same topic, move to a new required slot.
   - Do not repeat "thank you for sharing" as an opener.
   ```

2. **`console-ui/src/workflow_probe/recorder.py`** — add conversation-quality assertions:
   - `intake_response_avg_words` — compute average character/word count per assistant message
   - `intake_leading_question_count` — count therapist messages containing embedded interpretations
   - `intake_progress_language_count` — count messages containing banned progress terms
   - `intake_repeated_opener_count` — count consecutive messages starting with "thank you for"

3. **`tests/unit/test_trio_intake_agent.py`** — add assertion test: intake prompt contains verbosity constraint text.

---

### P0-5: Harden the user simulator (B4)

**Severity:** High
**Assessment ref:** B4 (lines 577-615)

#### Root code
- `console-ui/src/llm_user_simulator.py` — `LocalLLMUserSimulator`, `_build_prompt()` (line 314-353), system prompt (line 132-140)
- `console-ui/scenarios/workflow-probes/first_session_smoke.json` — persona definition (line 4-15)

#### Gap analysis
The simulator's system prompt is minimal with no anti-mirroring, anti-suggestibility, or persona-stability constraints. The simulator rapidly produces emotionally articulate, therapy-aligned responses that mirror the therapist's language.

#### Changes
1. **`console-ui/src/llm_user_simulator.py`** — update system prompt (line 132-140):
   ```
   You are a simulated user testing a console-based therapy application.
   You are the patient, not the therapist.
   Reply only with the next user message. Keep it concise, plausible, and human.
   Do not mention being an AI or that this is a test.
   Do not use markdown.

   Anti-mirroring rules:
   - Do not repeat the therapist's phrasing unless it was already part of your persona.
   - Your symptoms should not improve merely because the therapist suggests a frame.
   - At least 30% of turns should be partial, uncertain, ambivalent, or resistant.
   - Preserve stable traits and symptoms; do not show sudden breakthroughs unless earned over multiple turns.
   - Occasionally say "I don't know" or "I'm not sure."
   ```

2. **`console-ui/src/llm_user_simulator.py`** — in `_build_prompt()`, append a "persona stability" block that restates the persona traits and symptoms.

3. **`console-ui/scenarios/workflow-probes/first_session_smoke.json`** — change `persona.style` from `"cooperative, reflective, concise"` to `"guarded, occasionally evasive, concise"` for a more realistic baseline.

4. **`console-ui/src/workflow_probe/recorder.py`** — add `simulator_mirroring_score`: compute n-gram overlap between therapist-introduced terms and subsequent user responses.

---

## P1 — Important quality improvements

### P1-1: Separate facts from inferences in profile memory (A7)

**Severity:** Medium-high
**Assessment ref:** A7 (lines 366-398)

#### Root code
- `src/psychoanalyst_app/models/domain.py` — `UserProfile` (line 41-72): no provenance fields
- `src/psychoanalyst_app/agents/intake/extraction.py` — `extract_tier1_data()` (line 15-73)
- `src/psychoanalyst_app/agents/intake/prompts.py` — `TIER1_EXTRACTION_PROMPT` (line 52-130)
- `src/psychoanalyst_app/orchestration/profile_helpers.py` — `merge_user_profile()` (line 28-94)

#### Gap analysis
Profile fields like `family_atmosphere` and `relationship_to_work` store LLM inferences as plain strings. The extraction prompt says "Extract ONLY information explicitly mentioned by the patient. Do NOT infer or assume information not stated," but there's no structural enforcement.

#### Changes
1. **`src/psychoanalyst_app/models/domain.py`** — add a `ProfileField` wrapper:
   ```python
   class ProfileField(BaseModel):
       value: str | None = None
       source: Literal["patient_stated", "inference", "therapist_note"] = "inference"
       confidence: float = 0.5
       evidence_session_id: str | None = None
       evidence_message_index: int | None = None
       evidence_quote: str | None = None
       last_reviewed_with_patient: datetime | None = None
   ```

2. **`src/psychoanalyst_app/models/domain.py`** — update `UserProfile` to use `ProfileField` for interpretive fields (`family_atmosphere`, `relationship_to_work`, `social_context`, `current_situation`, etc.).

3. **`src/psychoanalyst_app/models/llm_outputs.py`** — update `PatientProfileExtract` sub-models to include `source` and `confidence` per field.

4. **`src/psychoanalyst_app/orchestration/profile_helpers.py`** — update `merge_user_profile()` to merge provenance-aware fields.

5. **Migration:** Add a DB migration to handle the new profile schema (JSON-encoded `ProfileField` dicts).

> NOTE: Schema change with migration implications. Consider starting with a lightweight approach: add `profile_source` as a parallel JSON column, and gradually migrate fields.

---

### P1-2: Add evidence spans to assessment recommendations (B6, B7)

**Severity:** Medium-high (B6), Medium (B7)
**Assessment ref:** B6 (lines 662-698), B7 (lines 700-733)

#### Root code
- `src/psychoanalyst_app/models/llm_outputs.py` — `StyleAssessmentOutput` (line 169-176)
- `src/psychoanalyst_app/agents/assessment/prompts.py` — `build_style_assessment_prompt()` (line 170-194)
- `src/psychoanalyst_app/agents/assessment/agent.py` — `_assess_style()` (line 206-248)

#### Gap analysis
`StyleAssessmentOutput` contains `assessment` (free text), `score` (float), and `key_topics` (list of strings). No evidence spans. Scores cluster at 0.92-0.95 with no calibration. Freudian explanation mentions "dreams, slips, and bodily reactions" not present in transcript.

#### Changes
1. **`src/psychoanalyst_app/models/llm_outputs.py`** — expand `StyleAssessmentOutput`:
   ```python
   class EvidenceBackedReason(BaseModel):
       claim: str
       evidence_quote: str | None = None
       evidence_message_index: int | None = None
       evidence_strength: Literal["direct", "indirect", "none"] = "none"

   class StyleAssessmentOutput(BaseModel):
       assessment: str = Field(..., min_length=1, max_length=2000)
       score: float = Field(..., ge=0.0, le=1.0)
       key_topics: list[str] = Field(default_factory=list, max_length=5)
       fit_reasons: list[EvidenceBackedReason] = Field(default_factory=list)
       mismatch_reasons: list[EvidenceBackedReason] = Field(default_factory=list)
       missing_information: list[str] = Field(default_factory=list)
   ```

2. **`src/psychoanalyst_app/agents/assessment/prompts.py`** — update prompt:
   - Require each `fit_reason` to include a transcript quote.
   - Require at least one `mismatch_reason`.
   - Score calibration: "Score 0.90+ only if clearly superior. Force scores to differ by at least 0.05 unless tied."
   - "Do not mention dreams, slips, transference, archetypes, or childhood trauma unless present in the transcript."

3. **`src/psychoanalyst_app/agents/assessment/agent.py`** — add validator: each `fit_reason` must have an `evidence_quote` or `evidence_strength != "none"`.

---

### P1-3: Style-specific response validators (B8)

**Severity:** Medium
**Assessment ref:** B8 (lines 735-764)

#### Root code
- `src/psychoanalyst_app/styles/cbt/therapist_prompt.txt`

#### Changes
1. **`src/psychoanalyst_app/styles/cbt/therapist_prompt.txt`** — add: "Each session must include at least one explicit CBT mechanism: thought record, automatic thought identification, cognitive distortion check, graded exposure, or behavioral experiment."

2. **`console-ui/src/workflow_probe/recorder.py`** — add probe assertion `cbt_response_contains_cbt_mechanism`: check therapy messages for CBT-specific terms.

---

### P1-4: Replace polling-heavy waits with job-state events (A2, A9)

**Severity:** Medium-high (A2), Medium (A9)
**Assessment ref:** A2 (lines 168-213), A9 (lines 429-447)

#### Root code
- `console-ui/src/workflow_probe/runner.py` — `wait_for_post_session_update()` (line 142-190)
- `console-ui/src/console_client.py` — `_follow_workflow()` (line 1099-1162): 2s poll interval
- `src/psychoanalyst_app/orchestration/response_handler.py` — `emit_job_status()` (line 513-541)

#### Changes
1. **`console-ui/src/workflow_probe/runner.py`** — compute and record `job_queued_duration_ms`, `job_running_duration_ms`, `llm_duration_inside_job_ms`, `polling_overhead_ms`.

2. **`console-ui/src/workflow_probe/recorder.py`** — add timing warnings: `wall_clock_runtime_high`, `polling_duration_high`, `llm_latency_undercoverage`.

3. **`console-ui/src/console_client.py`** — add "WebSocket-first" mode: when a `workflow_next_action` arrives via WebSocket with a different `state_signature`, process it immediately.

---

### P1-5: Clarify session-start briefing vs post-session handoff (A6)

**Severity:** Medium
**Assessment ref:** A6 (lines 336-363)

#### Root code
- `src/psychoanalyst_app/models/domain.py` — `Session.session_briefing`, `TherapyPlan.session_briefing`
- `src/psychoanalyst_app/orchestration/response_handler.py` — briefing persistence (line 275-318)
- `src/psychoanalyst_app/agents/therapist/agent.py` — briefing read (line 159-184)
- `src/psychoanalyst_app/orchestration/trio_conversation_manager.py` — `_with_latest_session_briefing()` (line 523-580)

#### Gap analysis
`Session.session_briefing` on a completed session is the output of that session, not the input the therapist used. `TherapyPlan.session_briefing` is the handoff for the next session. Semantically confusing.

#### Changes
1. **`src/psychoanalyst_app/models/domain.py`** — rename to `Session.post_session_handoff`, `TherapyPlan.next_session_briefing`. Add `Session.session_start_briefing`.

2. **`src/psychoanalyst_app/orchestration/response_handler.py`** — write to renamed fields.

3. **`src/psychoanalyst_app/orchestration/trio_conversation_manager.py`** — capture `session_start_briefing` used and persist to session row.

4. **Migration:** DB migration for column renames.

---

## P2 — Maintainability and polish

### P2-1: Decide `patient_analysis` table status (A8)

**Severity:** Low-to-medium
**Assessment ref:** A8 (lines 400-424)

#### Changes
1. Grep for `patient_analysis` references in code.
2. If unused: drop table, remove migration, remove code references.
3. If planned: add comment in schema.
4. If expected post-enrichment: add failing assertion to probe.

---

### P2-2: Concise therapy-opening constraints (B10)

**Severity:** Low-to-medium
**Assessment ref:** B10 (lines 799-820)

#### Changes
1. **`src/psychoanalyst_app/agents/therapist/prompts.py`** — add to initial prompt: "Start the session with at most 80 words: one sentence of continuity, one sentence naming the agreed focus, one open question."

---

### P2-3: Add diverse probe scenarios (A10)

**Severity:** Medium
**Assessment ref:** A10 (lines 449-467)

#### Changes
Add scenario files to `console-ui/scenarios/workflow-probes/`:
1. `chest_urgent_triage.json` — medically urgent chest symptoms
2. `uncooperative_user.json` — short, vague, contradicting answers
3. `avoidant_user.json` — changes topic, avoids questions
4. `alcohol_coping.json` — wine to sleep, tests alcohol follow-up
5. `style_tie_case.json` — multiple styles score similarly

---

### P2-4: Token accounting for all LLM calls (A9)

**Severity:** Medium
**Assessment ref:** A9 (lines 429-447)

#### Changes
1. **`src/psychoanalyst_app/services/llm_service.py`** — when `usage_metadata` is `None`, fall back to client-side token estimation.
2. **`console-ui/src/workflow_probe/recorder.py`** — track `prompt_tokens_logged` and `completion_tokens_logged` per phase.

---

### P2-5: Dedup non-wait workflow actions on client (A3)

**Severity:** Medium
**Assessment ref:** A3 (lines 216-252)

#### Root code
- `console-ui/src/console_client.py` — `_follow_workflow()` (line 1099-1162): dedup only for `wait` actions

#### Changes
1. **`console-ui/src/console_client.py`** — extend dedup to side-effectful actions: track `self.last_executed_action_signatures` keyed by `(action, state_signature)`. Skip execution if signature matches within the same session.

---

## Implementation order

| Phase | Issues | Est. effort | Dependencies |
|-------|--------|-------------|-------------|
| **Phase 1** | P0-4 (intake prompts), P0-5 (simulator), P0-1 (duration regex) | 2-3 days | None |
| **Phase 2** | P0-2 (medical triage), P0-3 (timing instrumentation) | 3-4 days | Phase 1 |
| **Phase 3** | P1-2 (recommendation evidence), P1-3 (CBT validator) | 2-3 days | Phase 1 |
| **Phase 4** | P1-1 (profile provenance), P1-5 (briefing semantics) | 4-5 days | Phase 2 |
| **Phase 5** | P1-4 (polling improvements), P2-5 (client dedup) | 2-3 days | Phase 2 |
| **Phase 6** | P2-1 through P2-5 | 3-4 days | Any |

---

## Risk assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Profile provenance schema change breaks existing data | High | Parallel `profile_source` column; gradual migration |
| Tighter duration regex rejects valid patient statements | Medium | Add test cases for valid duration expressions |
| Anti-mirroring prompt makes simulator too uncooperative | Medium | Tune strength; add "skeptical" and "cooperative" persona variants |
| Medical triage prompt feels alarming | Medium | Neutral, clinical language; gate behind explicit symptom triggers |
| Timing instrumentation adds overhead | Low | `time.perf_counter()` has minimal overhead |
| CBT mechanism requirement constrains therapist creativity | Medium | Require "at least one" mechanism, not all; allow integrative approaches |