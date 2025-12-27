"""Prompt construction helpers for the reflection agent."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from psychoanalyst_app.config import Settings
from psychoanalyst_app.models.data_models import PatientAnalysisVersion, Session, TherapyPlan
from psychoanalyst_app.prompts.reflection_prompts import (
    SESSION_BRIEFING_PROMPT,
    TIER2_ENRICHMENT_PROMPT,
    TIER3_CHANGE_DETECTION_PROMPT,
    TIER3_UPDATE_GENERATION_PROMPT,
)
def build_tier2_enrichment_prompt(session: Session) -> str:
    """Format the session transcript for Tier 2 enrichment extraction."""
    transcript_lines = []
    for message in session.transcript:
        role = "Therapist" if message.role == "assistant" else "Patient"
        transcript_lines.append(f"{role}: {message.content}")
    transcript = "\n".join(transcript_lines)
    return TIER2_ENRICHMENT_PROMPT.format(session_transcript=transcript)


def build_session_briefing_prompt(
    *,
    session_context: dict[str, Any],
    therapeutic_memory: dict[str, Any],
    plan_assessment: dict[str, Any] | None,
    session: Session,
    therapy_plan: TherapyPlan | None,
    config: Settings,
) -> str:
    """Create the structured session briefing prompt."""
    session_transcript = "\n".join(f"{msg.role}: {msg.content}" for msg in session.transcript)
    return SESSION_BRIEFING_PROMPT.format(
        total_sessions=therapeutic_memory.get("total_sessions", 0),
        relationship_quality=therapeutic_memory.get("relationship_quality", "building"),
        therapy_style=(
            therapy_plan.selected_therapy_style if therapy_plan else "Not specified"
        ),
        session_transcript=session_transcript,
        key_themes=json.dumps(session_context.get("key_themes", []), indent=2),
        emotional_state=session_context.get("emotional_state", "Not assessed"),
        insights=json.dumps(session_context.get("insights", []), indent=2),
        progress_indicators=json.dumps(
            session_context.get("progress_indicators", []), indent=2
        ),
        therapeutic_memory=json.dumps(therapeutic_memory, indent=2),
        plan_assessment=json.dumps(plan_assessment or {}, indent=2),
        tier4_initial_goals=json.dumps(
            therapy_plan.initial_goals if therapy_plan else [], indent=2
        ),
        tier4_current_progress=therapy_plan.current_progress if therapy_plan else "",
        tier4_planned_interventions=json.dumps(
            therapy_plan.planned_interventions if therapy_plan else [], indent=2
        ),
        tier4_status=therapy_plan.status if therapy_plan else "active",
        generated_at=datetime.now().isoformat(),
        last_session_id=session.session_id,
        last_session_date=session.timestamp.date().isoformat(),
        max_continuity_points=config.MAX_CONTINUITY_POINTS,
        max_key_themes=config.MAX_KEY_THEMES,
        max_progress_highlights=config.MAX_PROGRESS_HIGHLIGHTS,
        max_unresolved_issues=config.MAX_UNRESOLVED_ISSUES,
        max_suggested_questions=config.MAX_SUGGESTED_QUESTIONS,
        max_session_goals=config.MAX_SESSION_GOALS,
        min_narrative_length=config.MIN_NARRATIVE_LENGTH,
        max_narrative_length=config.MAX_NARRATIVE_LENGTH,
        max_observations_length=config.MAX_OBSERVATIONS_LENGTH,
        max_plan_notes_length=config.MAX_PLAN_NOTES_LENGTH,
    )


def _format_session_summary(session: Session) -> str:
    if getattr(session, "enriched", False) and getattr(session, "psychological_summary", None):
        affects = ", ".join(getattr(session, "dominant_affects", []))
        themes = ", ".join(getattr(session, "key_themes", []))
        return (
            f"Summary: {session.psychological_summary}\n"
            f"Affects: {affects}\n"
            f"Themes: {themes}"
        )
    return f"Session {session.session_id} with {len(session.transcript)} messages"


def build_tier3_detection_prompt(
    current_analysis: PatientAnalysisVersion, session: Session
) -> str:
    """Prepare the change detection prompt."""
    analysis_data = current_analysis.analysis_data
    current_formulation = (
        f"Theme: {analysis_data.current_focus.theme}\n"
        f"Salience: {analysis_data.current_focus.salience}\n"
        f"Primary Defenses: {', '.join(analysis_data.defenses.primary_defenses)}\n"
        f"Narratives: {', '.join(n.title for n in analysis_data.narratives)}\n"
        f"Risk Areas: {', '.join(analysis_data.orientation.risk_areas)}"
    )
    prompt = TIER3_CHANGE_DETECTION_PROMPT.format(
        current_version=current_analysis.version,
        current_analysis=current_formulation,
        session_summary=_format_session_summary(session),
    )
    return prompt


def build_tier3_update_prompt(
    current_analysis: PatientAnalysisVersion,
    session: Session,
    change_summary: str,
) -> str:
    """Create the prompt for generating an updated Tier 3 analysis."""
    analysis_data = current_analysis.analysis_data
    current_formulation = json.dumps(
        {
            "current_focus": {
                "theme": analysis_data.current_focus.theme,
                "salience": analysis_data.current_focus.salience,
            },
            "transference": {
                "idealization": analysis_data.transference.idealization,
                "devaluation": analysis_data.transference.devaluation,
                "boundaries": analysis_data.transference.boundaries,
                "other_patterns": analysis_data.transference.other_patterns,
            },
            "narratives": [
                {
                    "title": narrative.title,
                    "description": narrative.description,
                    "first_appeared": narrative.first_appeared,
                }
                for narrative in analysis_data.narratives
            ],
            "defenses": {
                "primary_defenses": analysis_data.defenses.primary_defenses,
                "defensive_style": analysis_data.defenses.defensive_style,
                "flexibility": analysis_data.defenses.flexibility,
            },
            "orientation": {
                "pacing": analysis_data.orientation.pacing,
                "risk_areas": analysis_data.orientation.risk_areas,
                "key_questions": analysis_data.orientation.key_questions,
            },
        },
        indent=2,
    )
    session_summary = _format_session_summary(session)
    return TIER3_UPDATE_GENERATION_PROMPT.format(
        current_version=current_analysis.version,
        current_analysis=current_formulation,
        session_summary=session_summary,
        change_summary=change_summary,
    )
