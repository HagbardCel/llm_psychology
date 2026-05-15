"""Prompt builders for assessment workflows."""

from __future__ import annotations


def build_style_assessment_prompt(
    *,
    assessment_prompt: str,
    style_id: str,
    session_summary: str,
) -> str:
    """Build the style-specific assessment prompt."""
    return f"""
{assessment_prompt}

        Based on the following intake session transcript, assess whether this patient
        would be a good candidate for {style_id.upper()} therapy:

Session Transcript:
{session_summary}

        Return a structured assessment for {style_id.upper()} therapy.

        Requirements:
        - assessment: 2-4 sentences explaining suitability and key indicators.
        - score: number between 0.0 and 1.0 (higher means stronger fit).
        - key_topics: 1-5 short topic phrases directly grounded in the transcript.

        Be specific, evidence-based, and avoid generic filler.
"""
