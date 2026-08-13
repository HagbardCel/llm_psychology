"""Shared SessionReview builders for integration and store tests."""

from __future__ import annotations

from jung.domain.session_artifacts import (
    PlanPatch,
    SessionAnalysis,
    SessionBriefing,
    SessionReview,
    SessionReviewGeneration,
)


def sample_review(**kwargs: object) -> SessionReview:
    defaults: dict[str, object] = {
        "analysis": SessionAnalysis(
            summary="Rich session summary.",
            key_themes=("anxiety", "sleep"),
            dominant_affects=("worry",),
            progress_indicators=("better sleep hygiene",),
        ),
        "briefing": SessionBriefing(
            narrative_handoff="Handoff narrative for the next session.",
            recommended_opening_focus="Focus on sleep routine.",
            continuity_points=("patient named sleep as priority",),
        ),
        "plan_recommendation": PlanPatch(current_progress="improved"),
        "generation": SessionReviewGeneration(
            analysis_model="m1",
            analysis_prompt_version="post-session-v6",
            update_model="m2",
            update_prompt_version="post-session-v6",
        ),
    }
    defaults.update(kwargs)
    return SessionReview(**defaults)
