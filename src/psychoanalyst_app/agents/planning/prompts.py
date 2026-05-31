"""Prompts and prompt builders for therapy planning."""

from __future__ import annotations

# Initial therapy plan creation prompt
CREATE_INITIAL_PLAN_PROMPT = """
You are an experienced clinical psychotherapist tasked with creating a comprehensive initial therapy plan.
Your goal is to formulate a structured treatment strategy based on the intake session and clinical best practices.

CONTEXT:
{context}

Please create a detailed therapy plan that includes:
1. Clinical Formulation: A brief synthesis of the client's presenting problems, history, and current functioning.
2. Risk Assessment: Any potential risks identified (e.g., self-harm, substance use) - if none, state "No immediate risks identified."
3. Primary Focus Areas: The main clinical issues to address.
4. Therapeutic Goals:
    - Immediate/Short-term goals (1-4 sessions)
    - Long-term goals (course of therapy)
5. Suggested Techniques/Interventions: Specific therapeutic modalities or techniques suited to this client.
6. Potential Themes to Explore: Underlying patterns or dynamics to investigate.

Provide your response in JSON format with the following structure:
{{
    "formulation": "Brief clinical formulation...",
    "risk_assessment": "Risk assessment findings...",
    "focus": "Main areas of focus...",
    "goals": "Specific therapeutic goals (short and long term)...",
    "techniques": "Suggested techniques...",
    "themes": "Key themes to explore..."
}}
"""

# Therapy plan update prompt
UPDATE_PLAN_PROMPT = """
You are an experienced clinical psychotherapist tasked with updating a therapy plan.
Review the latest session and the client's overall progress to adjust the treatment strategy.

CONTEXT:
{context}

Please update the therapy plan considering:
1. Clinical Progress: What shifts (positive or negative) have occurred?
2. New Insights: What new information or realizations emerged from the latest session?
3. Resistance/Transference: Are there any signs of resistance or transference/counter-transference dynamics?
4. Goal Adjustment: Do current goals need to be modified or marked as achieved?
5. Future Focus: What should be the priority for the next few sessions?

Provide your response in JSON format with the following structure:
{{
    "progress_note": "Summary of clinical progress...",
    "new_insights": "Key insights from recent sessions...",
    "dynamics": "Observations on resistance or transference...",
    "focus": "Updated main areas of focus...",
    "goals": "Updated therapeutic goals...",
    "techniques": "Updated suggested techniques...",
    "themes": "Emerging themes to explore..."
}}
"""


def build_initial_plan_prompt(
    *,
    context: str,
    therapy_style: str,
    reflection_prompt: str | None,
) -> str:
    """Build the initial therapy plan prompt."""
    if reflection_prompt:
        return f"""
{reflection_prompt}

Context for analysis:
{context}

Please create a comprehensive initial therapy plan based on this {therapy_style.upper()} approach.
Focus on the identified themes and provide specific, actionable elements.
"""

    return CREATE_INITIAL_PLAN_PROMPT.format(context=context)


def build_update_plan_prompt(
    *,
    context: str,
    therapy_style: str,
    reflection_prompt: str | None,
) -> str:
    """Build the therapy plan update prompt."""
    if reflection_prompt:
        return f"""
{reflection_prompt}

Context for plan update:
{context}

Please update the therapy plan based on this {therapy_style.upper()} approach.
Consider the therapeutic progress, emerging patterns, and current session insights.
"""

    return UPDATE_PLAN_PROMPT.format(context=context)
