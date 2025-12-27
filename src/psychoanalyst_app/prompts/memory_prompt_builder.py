"""Prompt builders for memory analysis workflows."""

from __future__ import annotations


def build_session_context_prompt(
    *, session_text: str, knowledge_context: str
) -> str:
    """Build the session context analysis prompt."""
    return f"""
            Analyze this therapy session transcript and extract key contextual information:

            Session Transcript:
            {session_text}

            Relevant Knowledge Context:
            {knowledge_context}

            Please provide a structured analysis including:
            1. Key themes discussed (3-5 main topics)
            2. Client's emotional state (one primary emotion)
            3. Important insights or breakthroughs
            4. Progress indicators (positive changes or developments)

            Respond in JSON format:
            {{
                "key_themes": ["theme1", "theme2", "theme3"],
                "emotional_state": "primary_emotion",
                "insights": ["insight1", "insight2"],
                "progress_indicators": ["indicator1", "indicator2"]
            }}
            """
