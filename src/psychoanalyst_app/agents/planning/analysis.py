"""Analysis helpers for the planning agent."""

from __future__ import annotations

from typing import Any

from psychoanalyst_app.models.data_models import TherapyPlan
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


def assess_update_necessity(session_context, memory, current_plan: TherapyPlan) -> bool:
    """Assess if plan update is necessary based on recent progress."""
    if len(session_context.insights) >= 2:
        return True

    current_themes = set(current_plan.plan_details.get("themes", "").split(", "))
    new_themes = set(session_context.key_themes)
    if len(new_themes - current_themes) >= 2:
        return True

    if len(session_context.progress_indicators) >= 2:
        return True

    if current_plan.version == 1 and len(memory.session_contexts) >= 3:
        return True

    return False


def identify_plan_changes(
    old_details: dict[str, Any], new_details: dict[str, Any]
) -> list[str]:
    """Identify specific changes between plan versions."""
    changes = []
    for key in ["focus", "goals", "techniques", "themes"]:
        old_value = old_details.get(key, "")
        new_value = new_details.get(key, "")
        if old_value != new_value:
            changes.append(f"{key}_updated")

    if "memory_insights" in new_details:
        changes.append("memory_insights_integrated")
    if "progress_indicators" in new_details:
        changes.append("progress_tracking_updated")
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

    emotional_trend = patterns.get("emotional_patterns", {}).get("recent_trend", "stable")
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
) -> dict[str, Any]:
    """Generate detailed effectiveness assessment."""
    strengths = []
    improvement_areas = []
    recommendations = []

    if effectiveness_score >= 0.7:
        strengths.append("Strong therapeutic progress evident")
        strengths.append("Good alignment between plan and outcomes")
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
    }


def recommend_theme_adjustments(
    plan: TherapyPlan, patterns: dict[str, Any]
) -> list[dict[str, Any]]:
    """Recommend theme-related adjustments."""
    recommendations = []
    theme_patterns = patterns.get("theme_patterns", {})
    dominant_themes = theme_patterns.get("dominant_themes", [])
    current_themes = set(plan.plan_details.get("themes", "").split(", "))

    for theme in dominant_themes[:2]:
        if theme not in current_themes:
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
                "description": "Consider introducing more advanced therapeutic techniques",
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

    if score >= 0.7:
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


def prioritize_recommendations(
    recommendations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Prioritize recommendations by importance."""
    priority_order = {"high": 0, "medium": 1, "low": 2}
    return sorted(
        recommendations,
        key=lambda x: priority_order.get(x.get("priority", "low"), 2),
    )

