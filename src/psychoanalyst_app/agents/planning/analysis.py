"""Analysis helpers for the planning agent."""

from __future__ import annotations

import re
from typing import Any

from psychoanalyst_app.models.domain import Session, TherapyPlan
from psychoanalyst_app.models.llm_outputs import PlanUpdate
from psychoanalyst_app.services.style_service import StyleService

from .models import PlanningStrategy


def recommend_therapy_style(session_context, relevant_knowledge) -> str:
    """Recommend appropriate therapy style based on session analysis."""
    themes = session_context.key_themes

    if any(theme in ["anxiety", "thoughts", "behavior"] for theme in themes):
        return "cbt"
    if any(theme in ["dreams", "unconscious", "childhood"] for theme in themes):
        return "freud"
    if any(theme in ["archetypes", "symbols", "meaning"] for theme in themes):
        return "jung"
    return "cbt"


def create_planning_strategy(
    style_service: StyleService,
    therapy_style: str,
    session_context,
) -> PlanningStrategy:
    """Create therapy planning strategy based on style and context."""
    style_config = style_service.get_style_pack(therapy_style)

    if style_config:
        focus_areas = session_context.key_themes[:3]
        techniques = ["active_listening", "reflection"]
        assessment_criteria = [
            "emotional_progress",
            "behavioral_changes",
            "insight_development",
        ]
    else:
        focus_areas = ["general_wellbeing"]
        techniques = ["supportive_therapy"]
        assessment_criteria = ["general_progress"]

    return PlanningStrategy(
        therapy_style=therapy_style,
        focus_areas=focus_areas,
        techniques=techniques,
        assessment_criteria=assessment_criteria,
    )


MIN_THERAPY_PATIENT_TURNS_FOR_PLAN_REVISION = 3

NORMALIZED_THEME_SYNONYMS = {
    "sleep disruption": {"sleep", "insomnia", "sleep hygiene", "sleep reset"},
    "work-related anxiety": {
        "work anxiety",
        "work-related stress",
        "deadline anxiety",
        "performance pressure",
        "meeting anxiety",
    },
    "panic": {"panic attack", "acute anxiety", "chest tightness"},
}


def assess_update_necessity(
    session_context,
    memory,
    current_plan: TherapyPlan,
    *,
    session: Session | None = None,
) -> bool:
    """Assess if plan update is necessary based on recent progress."""
    if session is not None:
        patient_turns = [
            message
            for message in session.transcript
            if getattr(message, "role", None) == "user"
        ]
        if (
            len(patient_turns) < MIN_THERAPY_PATIENT_TURNS_FOR_PLAN_REVISION
            and not _has_material_update_signal(session_context, patient_turns)
        ):
            return False

    if len(getattr(session_context, "insights", []) or []) >= 2:
        return True

    current_themes = {
        _canonical_theme(theme) for theme in (current_plan.themes or [])
    }
    new_themes = {
        _canonical_theme(theme)
        for theme in (getattr(session_context, "key_themes", []) or [])
    }
    if len(new_themes - current_themes) >= 2:
        return True

    if len(getattr(session_context, "progress_indicators", []) or []) >= 2:
        return True

    if (
        current_plan.version == 1
        and len(getattr(memory, "session_contexts", [])) >= 3
    ):
        return True

    return False


def _has_material_update_signal(session_context, patient_turns: list[Any]) -> bool:
    """Return True for concrete evidence that should bypass short-session gates."""
    combined_patient_text = " ".join(
        str(getattr(message, "content", "")).lower() for message in patient_turns
    )
    material_terms = (
        "suicide",
        "harm myself",
        "harm someone",
        "unsafe",
        "new diagnosis",
        "hospital",
        "medication",
        "my goal changed",
        "different goal",
        "i tried",
        "i practiced",
        "i won't do",
        "i cannot do",
    )
    if any(term in combined_patient_text for term in material_terms):
        return True
    if len(getattr(session_context, "risk_indicators", []) or []) > 0:
        return True
    return False


def _canonical_theme(value: str) -> str:
    normalized = _normalize_text(value)
    for canonical, synonyms in NORMALIZED_THEME_SYNONYMS.items():
        candidates = {
            item
            for item in (
                _normalize_text(canonical),
                *[_normalize_text(synonym) for synonym in synonyms],
            )
            if item
        }
        if normalized in candidates or any(item in normalized for item in candidates):
            return canonical
    return normalized


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", str(value).lower())).strip()


def identify_plan_changes(current_plan: TherapyPlan, update: PlanUpdate) -> list[str]:
    """Identify specific changes between plan versions."""
    changes = []
    values = {
        "focus": (current_plan.focus, update.focus),
        "goals": (current_plan.initial_goals, update.goals),
        "techniques": (current_plan.planned_interventions, update.techniques),
        "themes": (current_plan.themes, update.themes),
        "timeline": (current_plan.timeline, update.timeline),
    }
    for key, (old_value, new_value) in values.items():
        if old_value != new_value:
            changes.append(f"{key}_updated")
    return changes


def generate_update_rationale(session_context, memory, changes: list[str]) -> str:
    """Generate rationale for plan updates."""
    rationale_parts = []

    if "memory_insights_integrated" in changes:
        rationale_parts.append("Integrated insights from therapeutic memory")
    if "progress_tracking_updated" in changes:
        rationale_parts.append("Updated based on recent progress indicators")
    if session_context.insights:
        rationale_parts.append("Incorporated new session insights")
    if memory.relationship_quality in ["established", "strong"]:
        rationale_parts.append("Adjusted for deepening therapeutic relationship")

    return (
        "; ".join(rationale_parts)
        if rationale_parts
        else "Routine plan update based on session progress"
    )


def calculate_effectiveness_score(
    plan: TherapyPlan,
    memory,
    recent_context: dict[str, Any],
    patterns: dict[str, Any],
) -> float:
    """Calculate plan effectiveness score (0.0 to 1.0)."""
    score = 0.5

    progress_indicators = recent_context.get("insights", [])
    if progress_indicators:
        score += min(0.3, len(progress_indicators) * 0.1)

    emotional_trend = patterns.get("emotional_patterns", {}).get(
        "recent_trend",
        "stable",
    )
    if emotional_trend == "improving":
        score += 0.2
    elif emotional_trend == "declining":
        score -= 0.2

    relationship_quality = memory.relationship_quality
    quality_scores = {
        "new": 0.0,
        "building": 0.1,
        "developing": 0.2,
        "established": 0.3,
        "strong": 0.4,
    }
    score += quality_scores.get(relationship_quality, 0.0)
    return max(0.0, min(1.0, score))


def generate_effectiveness_assessment(
    plan: TherapyPlan,
    memory,
    recent_context: dict[str, Any],
    effectiveness_score: float,
    *,
    emotional_trend: str | None = None,
) -> dict[str, Any]:
    """Generate detailed effectiveness assessment."""
    strengths = []
    improvement_areas = []
    recommendations = []

    resolved_emotional_trend = (
        emotional_trend
        or recent_context.get("emotional_patterns", {}).get("recent_trend")
        or recent_context.get("emotional_trend")
        or "stable"
    )
    if effectiveness_score >= 0.7 and resolved_emotional_trend != "declining":
        strengths.append("Client shows engagement and insight")
        strengths.append("Plan remains aligned with current work")
    elif effectiveness_score >= 0.7:
        strengths.append("Client shows engagement, but symptoms remain active")
        improvement_areas.append("Continue stabilization before increasing ambition")
    elif effectiveness_score >= 0.5:
        strengths.append("Moderate progress observed")
        improvement_areas.append("Consider plan refinements")
    else:
        improvement_areas.append("Limited progress indicators")
        improvement_areas.append("Plan may need significant adjustment")
        recommendations.append("Review and update therapy approach")

    if memory.relationship_quality in ["established", "strong"]:
        strengths.append("Strong therapeutic relationship")
    else:
        improvement_areas.append("Continue building therapeutic rapport")

    insights = recent_context.get("insights", [])
    if len(insights) >= 2:
        strengths.append("Client demonstrating good insight development")
    else:
        recommendations.append("Focus on insight-building activities")

    return {
        "strengths": strengths,
        "improvement_areas": improvement_areas,
        "recommendations": recommendations,
        "effectiveness_score": effectiveness_score,
        "emotional_trend": resolved_emotional_trend,
    }


def recommend_theme_adjustments(
    plan: TherapyPlan, patterns: dict[str, Any]
) -> list[dict[str, Any]]:
    """Recommend theme-related adjustments."""
    recommendations = []
    theme_patterns = patterns.get("theme_patterns", {})
    dominant_themes = theme_patterns.get("dominant_themes", [])
    current_content = _plan_concept_set(plan)

    for theme in dominant_themes[:2]:
        if _canonical_theme(theme) not in current_content:
            recommendations.append(
                {
                    "type": "theme_addition",
                    "description": f"Consider adding '{theme}' as a focus theme",
                    "rationale": "Theme appears frequently in recent sessions",
                    "priority": "medium",
                }
            )
    return recommendations


def recommend_technique_adjustments(plan: TherapyPlan, memory) -> list[dict[str, Any]]:
    """Recommend technique-related adjustments."""
    recommendations = []
    if memory.relationship_quality in ["established", "strong"]:
        recommendations.append(
            {
                "type": "technique_advancement",
                "description": (
                    "Consider introducing more advanced therapeutic techniques"
                ),
                "rationale": "Strong therapeutic relationship allows for deeper work",
                "priority": "medium",
            }
        )
    return recommendations


def recommend_goal_adjustments(
    plan: TherapyPlan, effectiveness: dict[str, Any]
) -> list[dict[str, Any]]:
    """Recommend goal-related adjustments."""
    recommendations = []
    score = effectiveness.get("effectiveness_score", 0)
    emotional_trend = effectiveness.get("emotional_trend", "stable")

    if score >= 0.7 and emotional_trend != "declining":
        recommendations.append(
            {
                "type": "goal_progression",
                "description": "Consider setting more advanced therapeutic goals",
                "rationale": "High effectiveness suggests readiness for next level",
                "priority": "high",
            }
        )
    elif score < 0.4:
        recommendations.append(
            {
                "type": "goal_simplification",
                "description": "Consider simplifying current therapeutic goals",
                "rationale": "Lower effectiveness may indicate goals are too ambitious",
                "priority": "high",
            }
        )
    return recommendations


def _plan_concept_set(plan: TherapyPlan) -> set[str]:
    values: list[str] = [
        plan.focus,
        *(plan.themes or []),
        *(plan.initial_goals or []),
        *(plan.planned_interventions or []),
        *(plan.revision_recommendations or []),
    ]
    concepts = {_canonical_theme(value) for value in values if value}
    for value in values:
        normalized = _normalize_text(value)
        for canonical, synonyms in NORMALIZED_THEME_SYNONYMS.items():
            candidates = {
                item
                for item in (
                    _normalize_text(canonical),
                    *[_normalize_text(synonym) for synonym in synonyms],
                )
                if item
            }
            if any(candidate in normalized for candidate in candidates):
                concepts.add(canonical)
    return concepts


def prioritize_recommendations(
    recommendations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Prioritize recommendations by importance."""
    priority_order = {"high": 0, "medium": 1, "low": 2}
    return sorted(
        recommendations,
        key=lambda x: priority_order.get(x.get("priority", "low"), 2),
    )
