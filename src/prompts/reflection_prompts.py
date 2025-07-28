"""Prompt templates for the Reflection Agent."""

# Initial therapy plan creation prompt
CREATE_INITIAL_PLAN_PROMPT = """
You are an experienced psychotherapist tasked with creating an initial therapy plan 
based on the intake session transcript and relevant psychological knowledge.

{context}

Please create a structured therapy plan that includes:
1. Primary focus areas for therapy
2. Initial therapeutic goals
3. Suggested techniques or approaches
4. Potential themes to explore

Provide your response in JSON format with the following structure:
{{
    "focus": "Main areas of focus for therapy",
    "goals": "Specific therapeutic goals",
    "techniques": "Suggested therapeutic techniques",
    "themes": "Key themes to explore"
}}
"""

# Therapy plan update prompt
UPDATE_PLAN_PROMPT = """
You are an experienced psychotherapist tasked with updating a therapy plan 
based on the latest session and overall therapeutic progress.

{context}

Please update the therapy plan considering:
1. What new insights emerged from the latest session?
2. How has the client's presentation evolved?
3. What should be the focus for future sessions?
4. Are there any adjustments needed to goals or techniques?

Provide your response in JSON format with the following structure:
{{
    "focus": "Updated main areas of focus for therapy",
    "goals": "Updated therapeutic goals",
    "techniques": "Updated suggested techniques",
    "themes": "Emerging themes to explore"
}}
"""

# Session summary prompt
SESSION_SUMMARY_PROMPT = """
Please provide a concise summary of this therapy session:

{session_text}

Include:
1. Key themes discussed
2. Important insights or revelations
3. Client's emotional state
4. Progress made toward therapeutic goals
"""
