"""Shared SessionReview builders for integration and store tests."""

from __future__ import annotations

from jung.domain.session_artifacts import (
    InterventionCitation,
    PatientTurnCitation,
    PlanPatch,
    SessionAnalysis,
    SessionBriefing,
    SessionReview,
    SessionReviewGeneration,
)

# Known values shared by rich review fixtures and expected plan revisions.
SAMPLE_PLAN_FOCUS = "sleep hygiene"
SAMPLE_PLAN_THEMES = ("anxiety", "sleep")
SAMPLE_PLAN_GOALS = ("sleep better", "reduce worry")
SAMPLE_PLAN_PROGRESS = "improved"
SAMPLE_PLAN_INTERVENTIONS = ("homework", "tracking")
SAMPLE_PLAN_REVISIONS = ("continue tracking",)


def sample_review(**kwargs: object) -> SessionReview:
    """Comprehensive review for persistence round-trip tests."""
    defaults: dict[str, object] = {
        "analysis": SessionAnalysis(
            summary="Rich session summary.",
            key_themes=("anxiety", "sleep"),
            dominant_affects=("worry", "fatigue"),
            important_moments=("patient named sleep as priority",),
            patient_insights=("sleep anxiety is central",),
            progress_indicators=("better sleep hygiene",),
            unresolved_topics=("nighttime rumination",),
            intervention_citations=(
                InterventionCitation(
                    intervention_description="Sleep restriction framing",
                    therapist_sequence=2,
                    patient_sequence=None,
                ),
            ),
            patient_turn_citations=(PatientTurnCitation(patient_sequence=1),),
            safety_or_boundary_notes=("no acute risk identified",),
        ),
        "briefing": SessionBriefing(
            narrative_handoff="Handoff narrative for the next session.",
            recommended_opening_focus="Focus on sleep routine.",
            continuity_points=("patient named sleep as priority",),
            unresolved_issues=("nighttime rumination persists",),
            things_to_avoid=("minimizing sleep difficulty",),
            emotional_context=("fatigue and worry",),
        ),
        "plan_recommendation": PlanPatch(
            focus=SAMPLE_PLAN_FOCUS,
            themes=SAMPLE_PLAN_THEMES,
            goals=SAMPLE_PLAN_GOALS,
            current_progress=SAMPLE_PLAN_PROGRESS,
            planned_interventions=SAMPLE_PLAN_INTERVENTIONS,
            revision_recommendations=SAMPLE_PLAN_REVISIONS,
        ),
        "generation": SessionReviewGeneration(
            analysis_model="m1",
            analysis_prompt_version="post-session-v7",
            update_model="m2",
            update_prompt_version="post-session-v7",
        ),
    }
    defaults.update(kwargs)
    return SessionReview(**defaults)


def minimal_review(**kwargs: object) -> SessionReview:
    """Coherent no-op review for unrelated store setup."""
    defaults: dict[str, object] = {
        "analysis": SessionAnalysis(
            summary="Minimal session summary.",
            key_themes=("anxiety",),
        ),
        "briefing": SessionBriefing(
            narrative_handoff="Minimal handoff.",
            recommended_opening_focus="Check in on progress.",
        ),
        "plan_recommendation": PlanPatch(),
        "generation": SessionReviewGeneration(
            analysis_model="m1",
            analysis_prompt_version="post-session-v7",
            update_model="m2",
            update_prompt_version="post-session-v7",
        ),
    }
    defaults.update(kwargs)
    return SessionReview(**defaults)
