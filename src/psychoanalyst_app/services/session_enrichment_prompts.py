"""Prompt assembly for service-owned Tier 2 session enrichment."""

from __future__ import annotations

from psychoanalyst_app.models.domain import Session

TIER2_ENRICHMENT_PROMPT = """
Analyze the therapy session transcript and extract observable clinical data.
Return structured JSON matching the requested schema. Use only information
present in the transcript, avoid speculation, and use null for absent optional
fields.

SESSION TRANSCRIPT:
{session_transcript}
"""


def build_tier2_enrichment_prompt(session: Session) -> str:
    """Format a session transcript for Tier 2 enrichment extraction."""
    transcript_lines = []
    for message in session.transcript:
        role = "Therapist" if message.role == "assistant" else "Patient"
        transcript_lines.append(f"{role}: {message.content}")
    return TIER2_ENRICHMENT_PROMPT.format(
        session_transcript="\n".join(transcript_lines)
    )
