# Workflow Probe Assessment — `first_session_smoke` / `20260612T210041Z_first_session_smoke`

**Assessment date:** 2026-06-12
**Input artifacts reviewed:** `created_rows.json`, `run_manifest.json`, `trace.jsonl`, `summary.md`, `backend_llm_calls.jsonl`, `console.log`, `db_snapshot.sqlite`, `intake_completion_diagnostics.json`, `metadata.json`, `runtime.sqlite`, `timeline.md`, `transcript.md`.

## Executive summary

The probe is a **real functional pass**, not a false pass. The workflow successfully created a profile, completed intake, generated assessment recommendations, selected a therapy style, generated an initial plan, started a therapy session, ended the session, enriched the session, and produced a revised active plan. The persisted plan lineage is coherent: plan v1 was used by the therapy session and then superseded by active plan v2.

However, this should be interpreted as a **smoke-test pass**, not as evidence that the workflow is robust, clinically polished, or latency-ready. The most important findings are:

1. **The pass criteria are too permissive.** They verify that the workflow completes, but they miss clinically and UX-relevant problems: excessive therapist verbosity, leading/suggestive intake, unearned progress claims, weak medical triage after “urgent” chest tightness, and unsupported slot coverage.
2. **Timing instrumentation is misleading.** Logged LLM phase latency is much lower than user-visible latency. The strongest example is the first therapy response: transcript latency from user message to assistant message is ~57.1 s, while `backend_llm_calls.jsonl` reports only ~2.0 s for `therapy_response`. This suggests missing time-to-first-token, prompt-eval, queueing, streaming, or blocking overhead in the instrumentation.
3. **The user simulator is too suggestible.** It mirrors the therapist’s language and quickly converts therapist suggestions into “breakthroughs,” producing unrealistically cooperative therapeutic progress.
4. **The style-selection layer lacks discrimination.** CBT and Freudian approaches both scored `0.95`, Jung scored `0.92`, and the Freudian explanation includes material not present in the transcript, such as willingness to engage with dreams and slips.
5. **The data layer persists inferred psychological content as if it were fact.** Profile fields such as family atmosphere and relationship-to-work contain plausible inferences, but lack evidence spans, confidence, or explicit/inferred provenance.
6. **Post-session processing completes, but slowly and opaquely.** The run spent ~189.4 s polling for post-session completion, while logged `post_session_update` LLM time was ~42.9 s. The remaining time is not explained by the current artifacts.

## Run facts

| Item | Value |
|---|---:|
| Overall status | `PASS` |
| Scenario | `first_session_smoke` |
| Run id | `20260612T210041Z_first_session_smoke` |
| Backend/user-simulator model shown in logs | `unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M` |
| Sessions created | 2: one intake, one therapy |
| Intake patient turns | 12 |
| Final workflow state | `plan_update_complete` |
| Final completion decision | `complete_intake` |
| Plans created | 2: v1 superseded, v2 active |
| LLM finished calls | 26 |
| Logged total LLM latency | 98.0 s |
| Wall-clock runtime | 707.0 s |
| Post-session polling | 96 polls / 189.4 s |
| Unphased LLM calls | 0 |

## What worked well

### Functional workflow

The core workflow now behaves much better than the earlier stuck-intake failure mode:

- Profile creation succeeded.
- WebSocket connection succeeded.
- Intake started and completed.
- Assessment recommendations were generated and persisted.
- Style selection occurred before therapy.
- Therapy session started with a linked plan.
- Session ending triggered post-session update.
- Active plan v2 superseded v1 with explicit lineage.
- Final persisted user status is `PLAN_UPDATE_COMPLETE`.
- No backend fallback response appeared in the transcript.
- No user-simulator fallback was used.

### Persistence and lineage

The plan lineage is especially important and appears structurally sound:

| Plan | Version | Status | Used by session | Supersedes | Superseded by |
|---|---:|---|---|---|---|
| `ab55beeb-0d01-4790-835a-9d401c7a9008` | 1 | `superseded` | therapy session | — | `c5711dfc-60d5-4974-a399-2b000c143570` |
| `c5711dfc-60d5-4974-a399-2b000c143570` | 2 | `active` | none yet | `ab55beeb-0d01-4790-835a-9d401c7a9008` | — |

This is the right model: historical sessions preserve the plan they actually used, while the profile links to the latest active plan.

### Therapy response constraints

The therapy response passes the current quality gates:

- Relevant to the patient’s topic: chest tightness / thought pattern.
- Under the current word limit.
- Contains a concrete next step.
- Does not repeat the opening.
- Does not expose system/backend artifacts.

The issue is not that the workflow is broken. The issue is that the current probe is still too shallow to detect several important product-quality and clinical-quality risks.

---

# A. Likely harness/backend improvements

These are issues that mostly require instrumentation, workflow logic, assertions, persistence schema changes, or backend behavior changes. A stronger model alone will not reliably fix them.

## A1. Logged LLM latency under-reports user-visible latency

**Severity:** High
**Evidence:** The run reports `therapy_response_ms = 2021.297 ms`, but the transcript timestamps show ~57.1 s between the therapy user message and the assistant response. Several intake responses also show ~28–31 s transcript delays after user messages, while individual logged streaming latencies are only a few seconds.

### Computed user-visible response delays from transcript

| session_type   |   assistant_index |   delay_s |   chars | snippet                                                                          |
|:---------------|------------------:|----------:|--------:|:---------------------------------------------------------------------------------|
| intake         |                 3 |       0.2 |     128 | What would you most want to be different as a result of therapy, and what would  |
| intake         |                 5 |       1.2 |     677 | Thank you for sharing that—really helpful. You mentioned chest tightness before  |
| intake         |                 7 |       1.8 |    1104 | Thank you for sharing that—your description of the tight band, the heat, and the |
| intake         |                 9 |      28.5 |    1313 | Thank you for sharing that—your experience before meetings is powerful and very  |
| intake         |                11 |      29.5 |    1246 | Thank you for sharing so clearly—your description of that tight knot, the heat,  |
| intake         |                13 |      29.8 |    1559 | Thank you for sharing that—what you’re describing is a very real and common patt |
| intake         |                15 |      29.7 |    1676 | Thank you for sharing that—your words carry such clarity. You said the knot form |
| intake         |                17 |      28.1 |    1026 | Thank you for sharing that—your shift from seeing the knot as a failure to seein |
| intake         |                19 |      29.9 |    1467 | Thank you for sharing that—what you’ve said now is so powerful. You said you wer |
| intake         |                21 |      29.8 |    1719 | You’ve already done such a deep and honest work with this—your awareness of the  |
| intake         |                23 |      28.2 |    1099 | Thank you for sharing that—your notice of a *tiny pause in your shoulders* is su |
| intake         |                25 |      31.7 |     333 | Thank you for your openness today. We have completed the initial intake and gat  |
| therapy        |                 3 |      57.1 |     869 | Thank you for sharing that — it’s powerful and deeply meaningful.    You’re righ |

### Logged backend LLM phase timings

| phase                   |   calls |   latency_s |   avg_latency_ms |   max_latency_ms |   prompt_tokens_logged |   completion_tokens_logged |
|:------------------------|--------:|------------:|-----------------:|-----------------:|-----------------------:|---------------------------:|
| assessment_generation   |       4 |        17.7 |             4428 |             6315 |                      0 |                          0 |
| initial_plan_generation |       1 |         7.8 |             7806 |             7806 |                      0 |                          0 |
| intake_response         |      10 |        24.5 |             2453 |             3450 |                      0 |                          0 |
| post_session_update     |       9 |        42.9 |             4762 |            12468 |                    594 |                        699 |
| therapy_opening         |       1 |         3   |             3034 |             3034 |                      0 |                          0 |
| therapy_response        |       1 |         2   |             2021 |             2021 |                      0 |                          0 |

### Assessment

The likely cause is that `backend_llm_calls.jsonl` measures only part of streaming generation, probably from first received chunk to finish, and omits one or more of:

- request construction time;
- local-server queueing;
- prompt evaluation / prefill;
- time to first token;
- socket / stream setup;
- response persistence after generation;
- API endpoint blocking around plan generation or enrichment.

This makes the timing assertions much weaker than they appear. A run can pass `timing_therapy_response_ms` while still being slow from the user’s point of view.

### Concrete fixes

1. **Log full request lifecycle for every LLM call:**

   ```text
   request_created_at
   request_sent_at
   response_headers_at
   first_token_at
   final_token_at
   parse_complete_at
   persisted_at
   ```

2. **Report derived timing fields:**

   ```text
   queue_or_prefill_ms = first_token_at - request_sent_at
   stream_decode_ms    = final_token_at - first_token_at
   parse_ms            = parse_complete_at - final_token_at
   persistence_ms      = persisted_at - parse_complete_at
   total_wall_ms       = persisted_at - request_created_at
   ```

3. **Make assertions use user-facing wall time**, not only internal generation latency:

   - `therapy_response_user_visible_ms < threshold`
   - `intake_response_p95_user_visible_ms < threshold`
   - `initial_plan_user_visible_ms < threshold`
   - `post_session_update_user_visible_ms < threshold`

4. **Capture prompt and completion tokens for all call types**, including streaming and structured-output calls. If the OpenAI-compatible server does not return usage, count locally with the model tokenizer or with an approximation.

---

## A2. Polling-based workflow waits are slow and noisy

**Severity:** Medium-high
**Evidence:** The assessment wait used 45 polling iterations over ~88.5 s. Post-session state polling used 96 polls over ~189.4 s. The final run passed, but the console log shows repeated `GET /api/user/status` calls every ~2 s during post-session update.

### Assessment

Polling is acceptable for a smoke harness, but it obscures where time is spent and creates a noisy trace. It also makes it hard to distinguish:

- real backend processing time;
- LLM latency;
- background-job scheduling delay;
- polling interval delay;
- stuck jobs that eventually succeed;
- jobs that are complete but not reflected in status promptly.

### Concrete fixes

1. Add a **job-state endpoint** for assessment, enrichment, and plan update:

   ```text
   /api/jobs/{job_id}
   status: queued | running | llm_wait | db_write | complete | failed
   started_at
   updated_at
   current_step
   llm_call_ids
   last_error
   ```

2. Emit **WebSocket job-complete events** rather than relying on repeated status polling.

3. In the harness, collect:

   - job queued duration;
   - job running duration;
   - LLM duration inside the job;
   - DB write duration;
   - polling overhead.

4. Add an assertion such as:

   ```text
   post_session_polling_overhead_ms < 0.2 * post_session_update_wall_ms
   ```

---

## A3. Duplicate logical workflow actions are delivered through WebSocket and HTTP poll

**Severity:** Medium
**Evidence:** The trace shows repeated logical actions for the same state signature via both `websocket` and `http_poll`: `start_intake`, `select_therapy_style`, `start_therapy`, and `continue_therapy`.

### Assessment

The run passes because the backend appears idempotent, but dual-delivery is risky:

- The console trace becomes harder to interpret.
- The probe may accidentally execute duplicate actions in less controlled scenarios.
- Future actions with side effects could be double-applied.
- Assertions may count logical actions incorrectly if they do not deduplicate by state signature.

### Concrete fixes

1. Define a canonical deduplication key:

   ```python
   dedupe_key = (user_id, session_id, workflow_state, action, state_signature)
   ```

2. In the harness, record both:

   - raw deliveries;
   - deduplicated logical actions.

3. Add assertions:

   ```text
   no_duplicate_side_effectful_action_per_state_signature
   workflow_action_raw_delivery_sources_recorded
   workflow_action_logical_count_expected
   ```

4. Consider making the console client choose one control plane for next-action consumption: WebSocket for live mode, HTTP polling only as fallback.

---

## A4. Intake completion marks `duration` covered without transcript evidence

**Severity:** High
**Evidence:** `intake_completion_diagnostics.json` lists `duration` in `covered_slots`, but the transcript contains no clear question such as “How long has this been happening?” and no patient answer giving symptom duration.

### Assessment

This is a strong example of a false-positive slot coverage assertion. The intake completion logic likely treats repeated trigger sequencing as “duration” or infers duration from phrases like “now” / “as a kid,” but the required clinical-history slot is not actually covered.

### Concrete fixes

1. Require slot coverage to include an evidence span:

   ```json
   {
     "slot": "duration",
     "status": "covered",
     "evidence_message_index": 12,
     "evidence_quote": "...",
     "explicitness": "explicit"
   }
   ```

2. Disallow `covered` for hard slots without direct patient evidence.

3. Add a diagnostic artifact:

   ```json
   "slot_evidence": {
     "duration": {
       "status": "missing",
       "reason": "No patient statement specifies onset or duration"
     }
   }
   ```

4. Add assertions:

   ```text
   intake_duration_slot_has_explicit_evidence
   intake_functional_impairment_slot_has_explicit_evidence
   intake_coping_slot_has_explicit_evidence
   ```

5. Consider making onset/duration a required slot for chest tightness/anxiety intake.

---

## A5. Medical-risk handling for “urgent” chest tightness is too weak

**Severity:** High
**Evidence:** The first user message says chest tightness “feels urgent sometimes,” especially before meetings. The intake acknowledges physical symptoms but does not visibly follow up with medical red flags, prior medical assessment, or guidance to seek urgent care if symptoms are acute/severe/new.

### Assessment

For a therapy-oriented app, chest tightness can be anxiety-related, but it is also a medically significant symptom. The current assistant moves quickly into psychological formulation. That may be acceptable only if a medical triage path has already ruled out immediate risk. The probe should test this explicitly.

### Concrete fixes

1. Add a **medical red-flag micro-flow** when a user reports chest tightness, chest pain, faintness, severe shortness of breath, new neurological symptoms, or “medically urgent” sensations.

2. Minimal required follow-up:

   - Is this new, severe, worsening, or unlike previous anxiety symptoms?
   - Any shortness of breath, fainting, radiating pain, sweating, nausea, or cardiac history?
   - Has a medical professional evaluated it?
   - If acute/severe/new: seek urgent medical care / emergency services.

3. Add assertions:

   ```text
   chest_tightness_urgent_triggers_medical_triage
   urgent_physical_symptom_not_purely_psychologized
   medical_triage_has_clear_escalation_language
   ```

4. Store medical-triage outcome separately from psychological formulation.

---

## A6. The plan/session briefing semantics are ambiguous

**Severity:** Medium
**Evidence:** The therapy session row has a `session_briefing` field populated after the session, and the active plan v2 also contains that briefing. The therapy session used plan v1, which did not have a session briefing at start.

### Assessment

The stored briefing is useful, but semantically it is a **post-session handoff**, not the briefing that was available to the just-finished therapy session. The field name `session_briefing` may confuse future analysis and assertions.

### Concrete fixes

1. Rename or split fields:

   ```text
   session_start_briefing
   post_session_handoff
   next_session_briefing
   ```

2. Persist the actual briefing used at session start separately from the briefing generated after session end.

3. Add assertions:

   ```text
   therapy_session_start_briefing_matches_plan_available_at_start
   post_session_handoff_generated_after_session_end
   next_session_briefing_attached_to_active_plan
   ```

---

## A7. Profile fields mix facts and inferences without provenance

**Severity:** Medium-high
**Evidence:** The profile stores fields such as `family_atmosphere = Distant or high-pressure...` and `relationship_to_work = Work-related anxiety stems from...`. These are plausible but interpretive. The raw transcript does not directly establish the family atmosphere, parents’ relationship quality, or causal certainty.

### Assessment

This is risky for longitudinal therapy memory. It can cause later sessions to treat model interpretations as established patient facts.

### Concrete fixes

Use structured memory with provenance:

```json
{
  "field": "family_atmosphere",
  "value": "Possibly high-pressure / emotionally suppressive",
  "source": "inference",
  "confidence": 0.55,
  "evidence": [
    {
      "session_id": "2f536aa4-5b7a-4447-96de-d1c3b11c79db",
      "message_index": 18,
      "quote": "I was told to be quiet and strong—never cry, never show fear."
    }
  ],
  "last_reviewed_with_patient": null
}
```

Add a hard rule: **never promote inferred causal interpretations into profile fact fields without marking them as inference.**

---

## A8. `patient_analysis` table remains empty

**Severity:** Low-to-medium
**Evidence:** Both SQLite snapshots contain a `patient_analysis` table with zero rows.

### Assessment

This may be intentional, but for a lean local-laptop tool it is suspicious. It may represent either a future feature, a stale schema artifact, or a missing write path.

### Concrete fixes

1. Decide explicitly:

   - If unused: remove table/migration/code references.
   - If planned: create an assertion that explains why zero rows are expected.
   - If expected after enrichment: add a failing assertion.

2. For maintainability, document table ownership:

   ```text
   patient_analysis: currently unused / reserved / deprecated
   ```

---

## A9. Timing warnings are not sensitive enough

**Severity:** Medium
**Evidence:** `summary.md` reports no timing warnings, despite ~707 s wall-clock runtime and ~189 s post-session polling.

### Assessment

The timing-warning system currently confirms that individual recorded phase timings are below thresholds, but not that the user-facing workflow is fast enough. It therefore misses the practical bottlenecks.

### Concrete fixes

Add warning categories:

| Warning | Trigger |
|---|---|
| `wall_clock_runtime_high` | total runtime exceeds scenario budget |
| `polling_duration_high` | polling exceeds threshold |
| `llm_latency_undercoverage` | transcript user→assistant delay >> logged LLM latency |
| `ttft_high` | time-to-first-token exceeds threshold |
| `structured_output_slow` | structured-output generation exceeds threshold |
| `api_endpoint_blocking_high` | POST action takes too long before returning |

---

## A10. The test mostly verifies happy-path completion

**Severity:** Medium
**Evidence:** All 59 assertions pass, but several serious qualitative issues remain undetected.

### Concrete fixes

Add negative/edge-case probes:

1. **Ambiguous chest symptoms:** user says chest tightness feels medically urgent.
2. **Uncooperative user:** short, vague, contradicting, avoids questions.
3. **Noisy user:** changes topic, answers only half the question.
4. **Alcohol coping:** user uses wine to sleep repeatedly.
5. **Style tie case:** multiple styles score similarly.
6. **Long-context session:** enough history to stress prompt eval and session memory.
7. **Slow local model path:** assert user-visible latency and TTFT.

---

# B. Likely stronger-model / better-prompt improvements

These issues are mainly conversational-quality, reasoning-quality, or generation-control problems. Some should still be guarded by assertions, but they are likely improved by better prompting, style-specific instructions, better local models, or a less suggestible simulator.

## B1. Intake is too verbose and repetitive

**Severity:** Medium-high
**Evidence:** The intake assistant averaged ~1,043 characters per message. It repeatedly opens with variants of “Thank you for sharing...” and often includes meta-commentary about what the intake is doing.

### Assessment

This is not user-like or therapist-like. It makes the session feel scripted and slows down information gathering. It also masks missing coverage: long reflections give an impression of depth while asking too few concrete history questions.

### Concrete prompt fixes

Use an intake prompt constraint like:

```text
During intake:
- Ask at most 1–2 questions per turn.
- Keep responses under 120 words unless safety requires more.
- Do not include process meta-commentary such as “this helps us understand...”.
- Do not mention remaining time unless the user asks.
- Prefer neutral, open questions.
- Do not make breakthrough/progress claims.
- Move to a new required slot after two consecutive turns on the same topic.
```

### Harness assertions

```text
intake_response_max_words
intake_response_max_questions
intake_no_repeated_thank_you_opener
intake_no_time_meta
intake_topic_progression
```

---

## B2. The assistant asks leading questions and implants language

**Severity:** High
**Evidence:** The therapist introduces interpretations such as “body as signal,” “not failure,” “small victory,” and “being seen,” and the simulated patient then adopts those same frames.

### Assessment

The conversation appears therapeutically smooth, but much of the progress may be model-induced. This is especially problematic because the simulated user is also an LLM and may be highly suggestible.

### Concrete prompt fixes

For intake:

```text
Do not offer an interpretation before eliciting the patient's own framing.
Do not ask questions whose answer is embedded in the question.
Prefer: "What meaning do you make of that?"
Avoid: "Does that feel like your body is trying to protect you?"
```

For user simulation:

```text
You are not trying to help the therapist succeed.
Do not adopt the therapist's wording unless it genuinely fits your persona.
Sometimes answer incompletely, resist, clarify, or say you are unsure.
Preserve stable traits and symptoms; do not show sudden breakthroughs unless earned over multiple turns.
```

### Harness assertions

- Track n-gram overlap between therapist suggestions and subsequent user response.
- Flag sudden semantic adoption of therapist-introduced constructs.
- Add a “suggestibility score” to the probe summary.

---

## B3. Unearned progress and breakthrough claims

**Severity:** Medium-high
**Evidence:** Intake includes statements like “one of the most important breakthroughs,” “critical breakthrough,” and “That’s not just healing. That’s returning.” This occurs before behavioral evidence or sustained change.

### Assessment

This is emotionally inflated. It can produce unrealistic patient simulation and weakens clinical realism.

### Concrete fixes

1. Ban or restrict high-progress terms during intake:

   ```text
   breakthrough, healing, transformation, returning, profound shift, critical breakthrough
   ```

2. Replace with grounded reflection:

   ```text
   "That sounds like an important observation."
   "You are noticing a new detail about the experience."
   ```

3. Add assertion:

   ```text
   intake_no_unearned_progress_language
   ```

---

## B4. The user simulator is too cooperative and therapeutic

**Severity:** High
**Evidence:** The user simulator rapidly produces emotionally articulate, therapy-aligned responses:

- “I feel the knot as a signal, not a failure.”
- “It feels like a small victory.”
- “It’s like I’m being seen for the first time.”

### Assessment

This creates a false sense that the therapist is effective. A more realistic simulator should include hesitation, partial answers, uncertainty, avoidance, frustration, and inconsistent recall.

### Concrete fixes

1. Use a stronger simulator model than `Qwen3-4B-Instruct Q4_K_M` for probe realism, or at least run a second “skeptical simulator” profile.
2. Add simulator personas:

   - terse/anxious;
   - intellectualizing;
   - avoidant;
   - frustrated;
   - medically worried;
   - contradictory;
   - low insight;
   - high distress.

3. Add simulator constraints:

   ```text
   Do not resolve the central problem quickly.
   Do not turn therapist suggestions into self-insight unless asked multiple times and grounded in prior persona.
   Occasionally say "I don't know" or "I'm not sure."
   Maintain symptom severity unless an actual intervention has been practiced.
   ```

---

## B5. The intake gets stuck in a narrow somatic loop

**Severity:** Medium
**Evidence:** Much of the intake circles around chest tightness, knot, shoulders, breathing, and body signals. It does not clearly gather onset/duration, frequency, medical history, current support, broader work context, or concrete sleep/alcohol pattern.

### Assessment

The body-focused exploration is coherent, but too much time is spent deepening one frame. A stronger prompt should enforce slot progression.

### Concrete fixes

Implement an intake slot planner:

```text
Required slots:
1. immediate safety
2. medical-risk screen for physical symptoms
3. presenting problem
4. onset/duration/frequency
5. functional impairment
6. coping/substances
7. sleep impact
8. goals/preferences
9. relevant personal history
10. support/context
```

After each turn, the model should receive:

```json
{
  "covered_slots": [...],
  "missing_required_slots": [...],
  "next_best_slot": "duration",
  "allowed_question": "How long has this been happening, and how often does it occur?"
}
```

---

## B6. Therapy style scoring lacks calibration and discrimination

**Severity:** Medium-high
**Evidence:** CBT and Freud both receive `0.95`; Jung receives `0.92`. This is implausibly clustered and does not force a meaningful recommendation.

### Assessment

The style recommender is producing “everything fits” outputs. It also overstates evidence for each modality. For a product workflow, similar scores make selection less meaningful.

### Concrete fixes

1. Use a comparative rubric:

   ```text
   Score 0.90+ only if the style is clearly superior for this patient's stated goals.
   Penalize missing evidence.
   Penalize styles requiring material not elicited.
   Require one reason against each style.
   Force scores to differ by at least 0.05 unless explicitly marked as a tie.
   ```

2. Store normalized criteria:

   ```json
   {
     "style_id": "cbt",
     "goal_fit": 0.95,
     "patient_preference_fit": 0.80,
     "evidence_fit": 0.85,
     "risk_or_mismatch": 0.20,
     "overall": 0.86,
     "evidence_quotes": [...]
   }
   ```

3. Add assertion:

   ```text
   style_scores_are_calibrated_or_explicitly_tied
   style_recommendations_have_evidence_spans
   ```

---

## B7. Assessment recommendations contain unsupported claims

**Severity:** Medium
**Evidence:** The Freudian explanation says the patient is willing to engage with “dreams, slips, and bodily reactions.” Dreams and slips do not appear in the intake transcript.

### Assessment

This is a classic evidence-grounding failure. It may be small in this run, but it can compound over time if unsupported claims are persisted into plans or profile memory.

### Concrete fixes

1. Add a style-recommendation validator:

   ```text
   Every concrete claim must be either:
   - backed by a quote/span from transcript, or
   - explicitly marked as a general modality description, not patient-specific evidence.
   ```

2. Prompt:

   ```text
   Do not mention dreams, slips, transference, archetypes, childhood trauma, or family dynamics unless present in the transcript.
   ```

3. Add automated phrase checks for common unsupported modality clichés.

---

## B8. CBT session content is only partially CBT-specific

**Severity:** Medium
**Evidence:** The therapy response focuses on “body signal,” “I’m alive,” “I’m safe,” and somatic noticing. It includes a concrete check-in, but less explicit CBT structure: no automatic thought, belief, evidence, alternative thought, exposure plan, or behavioral experiment framing.

### Assessment

The response is supportive and relevant, but the selected style was CBT. The output blends CBT with somatic/ACT-like language. This may be desirable clinically, but the system should be explicit if it is using integrative CBT.

### Concrete fixes

For CBT, require one of:

- thought record;
- automatic thought identification;
- cognitive distortion check;
- graded exposure/behavioral experiment;
- situation-thought-feeling-body-behavior chain;
- sleep/alcohol behavior plan.

Example preferred response shape:

```text
Situation: opening email.
Body: tight chest, shoulder pause.
Automatic thought: "I must stay strong or I fail."
Alternative thought: "My body is alerting me; I can take one small action."
Experiment: open email, name one sensation, write the automatic thought, attend first 2 minutes of meeting.
```

Add assertion:

```text
cbt_response_contains_cbt_mechanism
```

---

## B9. Alcohol-for-sleep is under-addressed

**Severity:** Medium
**Evidence:** The user reports using wine to sleep and feeling more anxious afterward. The intake explores it briefly but does not gather quantity/frequency, dependency risk, or a concrete safer sleep plan during intake.

### Assessment

This is an important symptom-maintenance loop and potential health risk. It should not be buried under the body-signal formulation.

### Concrete fixes

Prompt the intake model to ask:

- How often do you use wine to sleep?
- How much?
- What happens on nights without it?
- Any withdrawal-like anxiety or rebound insomnia?
- Would you be willing to test a non-alcohol sleep routine?

Add assertions:

```text
alcohol_sleep_coping_triggers_frequency_question
alcohol_sleep_coping_not_only_validated
```

---

## B10. The opening of therapy is too long and expository

**Severity:** Low-to-medium
**Evidence:** The therapy opening is 1,032 characters and explains CBT, focus, beliefs, and body signals before asking what the patient wants to discuss.

### Assessment

This is acceptable for a smoke test, but not ideal UX. A therapy session should resume with warmth and continuity, not a mini-lecture.

### Concrete prompt fix

Use:

```text
Start therapy sessions with:
1. one sentence of continuity;
2. one sentence naming the agreed focus;
3. one open question.
Max 80 words.
```

Example:

```text
"Last time we noticed that opening email triggers chest tightness and a freeze response, and that the small pause in your shoulders may be an early signal rather than a failure. Would you like to start today by looking at the next time that happened, or by practicing the email-opening check-in?"
```

---

# C. Recommended backlog

## P0 — Fix before treating this as a strong workflow pass

1. **Add evidence-backed intake slot coverage.**
   - `covered_slots` must include message indices and quotes.
   - `duration` should not pass in this run unless supported by transcript evidence.

2. **Add medical-triage handling for urgent chest tightness.**
   - The next assistant turn after the “urgent” symptom mention should ask red flags or provide escalation guidance.

3. **Instrument user-visible latency and TTFT.**
   - Current timing metrics materially understate latency.

4. **Reduce intake leadingness and progress inflation.**
   - Add prompt constraints and assertions for leading questions, excessive progress claims, and repeated “thank you for sharing.”

5. **Harden the user simulator.**
   - Make it less cooperative and less likely to mirror therapist-supplied interpretations.

## P1 — Important quality improvements

1. **Separate facts from inferences in profile memory.**
2. **Add evidence spans to assessment recommendations and plan updates.**
3. **Improve style-score calibration and tie handling.**
4. **Add style-specific response validators, especially for CBT.**
5. **Replace polling-heavy waits with job-state events or richer job telemetry.**
6. **Clarify session-start briefing vs post-session handoff semantics.**

## P2 — Maintainability and polish

1. Decide whether `patient_analysis` is unused/deprecated or expected.
2. Add concise therapy-opening constraints.
3. Add more diverse probe scenarios.
4. Add token accounting for all LLM calls.
5. Add aggregate quality metrics to `summary.md`.

---

# D. Suggested new assertions

## Workflow / backend assertions

```text
intake_slot_duration_has_explicit_evidence
intake_slot_coverage_all_hard_slots_have_evidence
urgent_chest_tightness_triggers_medical_triage
stream_response_ttft_logged
stream_response_total_wall_ms_logged
therapy_response_user_visible_ms_under_threshold
post_session_update_wall_ms_under_threshold
no_duplicate_side_effectful_workflow_action_per_state_signature
post_session_handoff_generated_after_session_end
session_start_briefing_available_before_session_start
profile_memory_inferences_marked_as_inferred
```

## Conversation-quality assertions

```text
intake_response_max_words
intake_response_max_questions
intake_no_repeated_thank_you_opener
intake_no_time_meta_commentary
intake_no_unearned_progress_language
intake_no_leading_interpretation_before_patient_evidence
style_recommendations_have_evidence_spans
style_scores_are_calibrated_or_explicitly_tied
cbt_response_contains_cbt_mechanism
alcohol_sleep_coping_triggers_frequency_question
```

## Simulator-quality assertions

```text
user_simulator_no_fallbacks
user_simulator_low_mirroring_of_therapist_terms
user_simulator_preserves_persona_stability
user_simulator_does_not_resolve_core_problem_too_fast
user_simulator_has_sufficient_variability_across_runs
```

---

# E. Concrete implementation sketches

## E1. Slot evidence schema

```python
class SlotEvidence(BaseModel):
    slot_id: str
    status: Literal["missing", "partial", "covered"]
    explicitness: Literal["explicit", "inferred", "not_present"]
    evidence_message_index: int | None = None
    evidence_role: Literal["user", "assistant"] | None = None
    evidence_quote: str | None = None
    confidence: float
    notes: str | None = None
```

Validation rule:

```python
for slot in hard_required_slots:
    assert slot.status == "covered"
    assert slot.explicitness == "explicit"
    assert slot.evidence_role == "user"
    assert slot.evidence_quote
```

## E2. Stream timing schema

```python
class LLMCallTiming(BaseModel):
    call_id: str
    phase: str
    call_type: str
    provider: str
    model: str
    request_created_at: datetime
    request_sent_at: datetime | None
    response_headers_at: datetime | None
    first_token_at: datetime | None
    final_token_at: datetime | None
    parsed_at: datetime | None
    persisted_at: datetime | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None

    @property
    def ttft_ms(self) -> float | None:
        ...

    @property
    def total_wall_ms(self) -> float | None:
        ...
```

## E3. Recommendation evidence schema

```python
class TherapyStyleRecommendation(BaseModel):
    style_id: str
    overall_score: float
    rank: int
    fit_reasons: list[EvidenceBackedReason]
    mismatch_or_caution: list[EvidenceBackedReason]
    missing_information: list[str]
    calibration_note: str

class EvidenceBackedReason(BaseModel):
    claim: str
    evidence_quote: str | None
    evidence_message_index: int | None
    evidence_strength: Literal["direct", "indirect", "none"]
```

## E4. User simulator anti-mirroring instruction

```text
You are simulating a patient, not collaborating with the therapist.
Do not repeat therapist phrases such as "signal", "small victory", "body speaking", or "seen" unless those phrases were already part of your persona.
Your symptoms should not improve merely because the therapist suggests a frame.
At least 30% of turns should be partial, uncertain, ambivalent, or resistant.
```

---

# F. Overall verdict

This probe is a **meaningful improvement** over a previously failing workflow: the backend no longer gets stuck in intake, and the persisted workflow artifacts are coherent. The plan-version lineage and final `PLAN_UPDATE_COMPLETE` state are especially encouraging.

The main next step is to stop treating a green smoke probe as sufficient. The workflow should now be hardened along three axes:

1. **Evidence-grounded state:** slots, profile memory, recommendations, and plans need quotes/provenance.
2. **User-visible performance:** measure wall latency, TTFT, polling overhead, and endpoint blocking.
3. **Conversation realism:** reduce leading intake behavior, prevent unearned “breakthroughs,” and use a less suggestible user simulator.

If these changes are implemented, the probe will become much more useful as a local-laptop regression test: not merely verifying that the tool completes, but verifying that it completes in a clinically safer, more realistic, and more maintainable way.
