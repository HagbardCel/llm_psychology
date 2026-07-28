---
owner: engineering
status: accepted
last_reviewed: 2026-07-21
review_cycle_days: 30
source_of_truth_for: Phase processor and LLM boundary decision
---

# ADR 0005: Phase processors and OpenAI-compatible gateway

## Decision

Retain `IntakeProcessor`, `AssessmentProcessor`, `TherapyProcessor`, and `PostSessionProcessor`; they return typed results and never persist, emit transport events, navigate workflow, construct dependencies, or call another processor. Note-taking, planning, and memory become helpers within intake/assessment/post-session behavior.

Only `llm/` imports the async OpenAI SDK. Its project-owned protocol is `stream_text(messages, policy)` and `generate_structured(messages, output_type, policy)`. `ModelPolicy` explicitly selects `json_schema`, `json_object`, or `prompt` structured-output mode. One correction attempt follows validation failure, then `invalid_llm_output` is returned.

## Consequences

Initial support targets Chat Completions-compatible local servers. Responses API, tool calling, native structured output, provider extensions, LangChain service graphs, RAG, and cloud rate-limiting are not application assumptions.

## Related canonical documentation

- [Target Architecture](../refactor/target-architecture.md)
