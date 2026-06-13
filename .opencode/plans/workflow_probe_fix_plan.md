# Workflow Probe Fix Plan

## Issues

Two assertions failed in the last probe run (`20260612T143502Z_first_session_smoke`):

| # | Assertion | Value | Expected |
|---|-----------|-------|----------|
| 1 | `therapy_response_has_concrete_next_step` | 0 terms matched | 1 |
| 2 | `timing_no_unphased_llm_calls` | 17 unphased | 0 |

---

## Issue 1: `therapy_response_has_concrete_next_step`

### Root Cause

The assertion (assertions.py:261-270) checks whether the first therapist response in the therapy session contains any of these substrings: `["notice", "map", "track", "breathe", "ground", "write"]`.

The therapist actually said: *"like taking a **breath** and whispering that phrase to yourself"* — using the noun "breath" instead of the verb "breathe". Since the check is a simple substring match, `"breathe"` is not found in `"breath"`.

The scenario config (`first_session_smoke.json`) does not override `therapy_response_concrete_step_terms`, so it uses the default list.

### Fix

**File:** `console-ui/src/workflow_probe/assertions.py`, lines 263-269

Add `"breath"` to the default `therapy_response_concrete_step_terms` list:

```python
await check(
    "therapy_response_has_concrete_next_step",
    any(
        term in disclosure_response.lower()
        for term in criteria.get(
            "therapy_response_concrete_step_terms",
            ["notice", "map", "track", "breathe", "breath", "ground", "write"],
        )
    ),
)
```

This is a minimal, low-risk fix. The noun and verb forms are semantically equivalent for this check, and the small language model (Qwen3-4B) naturally uses whichever form the prompt template encourages.

**Alternative considered (rejected):** Updating the continuation prompt to force the verb form. This would be fragile and could degrade response quality. Adding the term variant is the right tradeoff.

---

## Issue 2: `timing_no_unphased_llm_calls` — 17 unphased calls

### Root Cause

The recorder (`recorder.py:219-253`) counts an LLM call as "unphased" if its `phase` field is missing or empty in `backend_llm_calls.jsonl`. The assertion requires `unphased_count == 0`.

The problem is entirely in the **backend** — `phase=None` is not being set on LLM calls across several agent pathways. There are two categories:

#### Category A: Intake streaming responses (~10 calls)

`trio_conversation_manager.py:271-282`:

```python
phase=(
    "therapy_opening"
    if agent == "THERAPIST"
    and not any(message.role == "user" for message in context.message_history)
    else "therapy_response" if agent == "THERAPIST" else None
),
```

The `phase` is `None` for **all** non-THERAPIST agents. This covers intake session responses, which are the bulk of the unphased calls (the probe ran 11 intake turns through the LLM, each one a `stream_response` with `phase=None`).

**Fix:** Add a dedicated `intake_response` phase for intake agent streaming calls.

**File:** `src/psychoanalyst_app/orchestration/trio_conversation_manager.py`, lines 273-282

```python
phase=(
    "therapy_opening"
    if agent == "THERAPIST"
    and not any(message.role == "user" for message in context.message_history)
    else "therapy_response"
    if agent == "THERAPIST"
    else "intake_response"
    if agent == "INTAKE"
    else None
),
```

#### Category B: Structured output calls without phases (7 calls)

Four production call sites pass `phase=None` to `generate_structured_output_async`:

| File:Line | Context | Suggested Phase |
|-----------|---------|-----------------|
| `agents/intake/extraction.py:33` | `extract_tier1_data()` — post-intake patient profile extraction | `"intake_extraction"` |
| `services/session_enrichment.py:37` | Tier 2 session enrichment | `"session_enrichment"` |
| `agents/memory/agent.py:80` | Session analysis for memory | `"memory_analysis"` |
| `agents/therapist/deep_topic.py:34` | Deep topic detection signal | `"deep_topic_detection"` |

---

### Recommendation: Add phase at every call site

Add proper `phase=` arguments at all 5 call sites. No assertion changes needed — the strict `unphased == 0` check is correct, it just needs the backend to comply.

**Phase assignments:**

| Call Site | Phase | Rationale |
|-----------|-------|-----------|
| Intake streaming (`trio_conversation_manager.py`) | `"intake_response"` | Separate from therapy responses |
| `extract_tier1_data()` | `"intake_extraction"` | Structured extraction during intake |
| `session_enrichment.py` | `"session_enrichment"` | Post-session enrichment job |
| `memory/agent.py:80` | `"memory_analysis"` | Memory session analysis |
| `deep_topic.py:34` | `"deep_topic_detection"` | Therapist deep topic signal |

---

## Summary of Changes

| # | File | Change |
|---|------|--------|
| 1 | `console-ui/src/workflow_probe/assertions.py` | Add `"breath"` to default concrete step terms (line ~267) |
| 2 | `src/psychoanalyst_app/orchestration/trio_conversation_manager.py` | Add `intake_response` phase for INTAKE agent (lines ~273-282) |
| 3 | `src/psychoanalyst_app/agents/intake/extraction.py` | Add `phase="intake_extraction"` (line ~33) |
| 4 | `src/psychoanalyst_app/services/session_enrichment.py` | Add `phase="session_enrichment"` (line ~37) |
| 5 | `src/psychoanalyst_app/agents/memory/agent.py` | Add `phase="memory_analysis"` (line ~80) |
| 6 | `src/psychoanalyst_app/agents/therapist/deep_topic.py` | Add `phase="deep_topic_detection"` (line ~34) |

No new tests needed — the probe itself covers the full workflow. Run `make probe-console-deterministic` or `make probe-console-smoke` to verify.
