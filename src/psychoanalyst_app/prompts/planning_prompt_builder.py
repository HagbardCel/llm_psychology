"""Prompt builders for planning workflows."""

from __future__ import annotations

from psychoanalyst_app.prompts.reflection_prompts import (
    CREATE_INITIAL_PLAN_PROMPT,
    UPDATE_PLAN_PROMPT,
)


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
