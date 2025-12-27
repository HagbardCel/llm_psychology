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

        Please provide a brief assessment of why this patient might or might not be
        suitable for {style_id.upper()} therapy, focusing on the key indicators you
        see in the transcript.
"""
