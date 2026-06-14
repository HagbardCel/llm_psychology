"""Canonical LLM phase names used for metrics and probe diagnostics."""

from __future__ import annotations

from typing import Literal, TypeAlias

LLMPhase: TypeAlias = Literal[
    "intake_response",
    "intake_extraction",
    "intake_note_tracking",
    "assessment_style_scoring",
    "assessment_initial_formulation",
    "initial_plan_generation",
    "therapy_opening",
    "therapy_response",
    "therapy_deep_topic_detection",
    "session_enrichment",
    "session_summary",
    "memory_analysis",
    "plan_reflection",
    "tier1_profile_change_detection",
    "tier1_profile_update",
    "tier3_change_detection",
    "tier3_update",
]

INTAKE_RESPONSE: LLMPhase = "intake_response"
INTAKE_EXTRACTION: LLMPhase = "intake_extraction"
INTAKE_NOTE_TRACKING: LLMPhase = "intake_note_tracking"
ASSESSMENT_STYLE_SCORING: LLMPhase = "assessment_style_scoring"
ASSESSMENT_INITIAL_FORMULATION: LLMPhase = "assessment_initial_formulation"
INITIAL_PLAN_GENERATION: LLMPhase = "initial_plan_generation"
THERAPY_OPENING: LLMPhase = "therapy_opening"
THERAPY_RESPONSE: LLMPhase = "therapy_response"
THERAPY_DEEP_TOPIC_DETECTION: LLMPhase = "therapy_deep_topic_detection"
SESSION_ENRICHMENT: LLMPhase = "session_enrichment"
SESSION_SUMMARY: LLMPhase = "session_summary"
MEMORY_ANALYSIS: LLMPhase = "memory_analysis"
PLAN_REFLECTION: LLMPhase = "plan_reflection"
TIER1_PROFILE_CHANGE_DETECTION: LLMPhase = "tier1_profile_change_detection"
TIER1_PROFILE_UPDATE: LLMPhase = "tier1_profile_update"
TIER3_CHANGE_DETECTION: LLMPhase = "tier3_change_detection"
TIER3_UPDATE: LLMPhase = "tier3_update"

VALID_LLM_PHASES: frozenset[str] = frozenset(
    [
        INTAKE_RESPONSE,
        INTAKE_EXTRACTION,
        INTAKE_NOTE_TRACKING,
        ASSESSMENT_STYLE_SCORING,
        ASSESSMENT_INITIAL_FORMULATION,
        INITIAL_PLAN_GENERATION,
        THERAPY_OPENING,
        THERAPY_RESPONSE,
        THERAPY_DEEP_TOPIC_DETECTION,
        SESSION_ENRICHMENT,
        SESSION_SUMMARY,
        MEMORY_ANALYSIS,
        PLAN_REFLECTION,
        TIER1_PROFILE_CHANGE_DETECTION,
        TIER1_PROFILE_UPDATE,
        TIER3_CHANGE_DETECTION,
        TIER3_UPDATE,
    ]
)


def require_llm_phase(phase: str | None) -> LLMPhase:
    """Return a canonical phase or fail before any LLM call is attempted."""
    if phase is None or not str(phase).strip():
        raise ValueError("LLM phase is required")
    if phase not in VALID_LLM_PHASES:
        allowed = ", ".join(sorted(VALID_LLM_PHASES))
        raise ValueError(f"Unknown LLM phase: {phase!r}. Expected one of: {allowed}")
    return phase  # type: ignore[return-value]
