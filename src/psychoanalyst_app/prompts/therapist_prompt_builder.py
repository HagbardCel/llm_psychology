"""
Prompt composition helpers for the Psychoanalyst agent.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psychoanalyst_app.models.briefing_models import BriefingStatus
from psychoanalyst_app.models.data_models import TherapyPlan, UserProfile
from psychoanalyst_app.prompts.therapist_prompts import (
    CONTINUE_SESSION_PROMPT,
    INITIAL_SESSION_PROMPT,
)


def build_initial_prompt(
    *,
    user_name: str,
    plan_context: str,
    style_instructions: str,
) -> str:
    return INITIAL_SESSION_PROMPT.format(
        user_name=user_name,
        plan_context=plan_context,
        style_instructions=style_instructions,
    )


def build_continuation_prompt(
    *,
    plan_context: str,
    additional_knowledge: str,
    latest_message: str,
    style_instructions: str,
    time_prompt: str = "",
) -> str:
    return CONTINUE_SESSION_PROMPT.format(
        plan_context=plan_context,
        additional_knowledge=additional_knowledge,
        latest_message=latest_message,
        time_prompt=time_prompt,
        style_instructions=style_instructions,
    )


def build_resumption_prompt(
    user_profile: UserProfile,
    therapy_plan: TherapyPlan,
    briefing: dict[str, Any],
    status: BriefingStatus,
) -> str:
    narrative = briefing.get("narrative_handoff", "")
    observations = briefing.get("patient_observations", "")
    plan_notes = briefing.get("plan_progression_notes", "")
    relationship = briefing.get("relationship_quality", "building")
    session_number = briefing.get("session_count", 0) + 1
    recommended = briefing.get("recommended_approach", {})

    continuity_points = briefing.get("continuity_points", [])
    continuity_text = "\n".join([f"  - {point}" for point in continuity_points[:3]])

    key_themes = briefing.get("key_themes", [])
    high_priority_themes = [t for t in key_themes if t.get("priority") == "high"]
    themes_text = ", ".join([t.get("theme", "") for t in high_priority_themes[:3]])

    suggested_questions = recommended.get("suggested_questions", [])
    questions_text = "\n".join(
        [f"  {i + 1}. {q}" for i, q in enumerate(suggested_questions)]
    )

    prompt = f"""You are conducting a {therapy_plan.selected_therapy_style} therapy session. This is session #{session_number} with {user_profile.name}.

THERAPEUTIC CONTEXT:
Relationship Stage: {relationship.capitalize()}
Last Session Date: {briefing.get("last_session_date", "Recent")}

SUPERVISOR'S BRIEFING:
{narrative}

CLINICAL OBSERVATIONS FROM PREVIOUS SESSION:
{observations}

TREATMENT PLAN PROGRESSION:
{plan_notes}

EMOTIONAL STATE:
- Current: {briefing.get("emotional_summary", {}).get("last_session", "Not specified")}
- Trend: {briefing.get("emotional_summary", {}).get("trend", "Not specified")}
- Note: {briefing.get("emotional_summary", {}).get("note", "")}

CONTINUITY POINTS TO FOLLOW UP ON:
{continuity_text}

CURRENT HIGH-PRIORITY THEMES:
{themes_text if themes_text else "No specific themes identified"}

PROGRESS HIGHLIGHTS:
{chr(10).join([f"  ✓ {h}" for h in briefing.get("progress_highlights", [])[:3]])}

UNRESOLVED ISSUES REQUIRING ATTENTION:
{chr(10).join([f"  • {issue}" for issue in briefing.get("unresolved_issues", [])[:3]])}

RECOMMENDED APPROACH FOR THIS SESSION:
Tone: {recommended.get("opening_tone", "Warm and welcoming")}
Focus: {recommended.get("opening_focus", "General check-in")}
Avoid: {recommended.get("things_to_avoid", "Pushing too hard")}

Suggested Opening Questions (choose one or synthesize your own based on the above):
{questions_text}

Session Goals:
{chr(10).join([f"  {i + 1}. {g}" for i, g in enumerate(recommended.get("therapeutic_goals_for_session", []))])}

YOUR TASK:
The patient has just entered the session. They have not spoken yet. Based on the comprehensive briefing above, generate a natural, conversational opening greeting that:

1. Welcomes them back warmly and authentically
2. Demonstrates continuity by referencing something specific from your last session together
3. Acknowledges their emotional state or progress if appropriate
4. Invites them to begin speaking in an open-ended way
5. Maintains the recommended tone and focus

IMPORTANT CONSTRAINTS:
- Keep your greeting to 2-4 sentences
- Be specific and personal - reference actual themes or topics from the briefing
- Sound natural and conversational, not scripted or formulaic
- Don't overwhelm them with everything from the briefing - choose what feels most relevant
- Match the therapeutic style ({therapy_plan.selected_therapy_style}) in your language and approach

Generate your opening greeting now:"""

    if status == BriefingStatus.STALE:
        days_since = (
            datetime.now()
            - datetime.fromisoformat(
                briefing.get("generated_at", datetime.now().isoformat())
            )
        ).days
        prompt += f"""

IMPORTANT - STALE BRIEFING NOTICE:
It has been approximately {days_since} days since the last session. The briefing above may not reflect the patient's current state. When generating your greeting:

1. Acknowledge the time gap explicitly but gently
2. Don't assume they're in the same emotional place as the briefing suggests
3. Be more open-ended and exploratory rather than assuming continuity
4. Focus on "what's been on your mind recently" rather than specific past themes
5. Use the briefing as background context, not as current truth

Example approach: "Welcome back, {user_profile.name}. It's been a while since we last spoke. I'm curious to hear what's been on your mind recently."
"""

    return prompt
