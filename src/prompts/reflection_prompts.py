"""Prompt templates for the Reflection Agent."""

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

# Session summary prompt
SESSION_SUMMARY_PROMPT = """
Please provide a clinically oriented summary of this therapy session.

SESSION TRANSCRIPT:
{session_text}

Your summary should be structured as follows:
1. Presenting Issues: What did the client bring to the session today?
2. Key Themes: The main topics or underlying themes discussed.
3. Emotional State: The client's affect and emotional presentation during the session.
4. Interventions: Key interventions used by the therapist.
5. Client Response: How the client responded to interventions and the session process.
6. Plan for Next Session: Recommendations for the next appointment.
"""

# Session briefing prompt (for resuming sessions)
SESSION_BRIEFING_PROMPT = """You are a supervising psychoanalyst conducting a comprehensive review of a completed therapy session. Your role is to create a detailed "Session Briefing" that will be used by the therapist who conducts the next session with this patient.

PATIENT CONTEXT:
- Total Sessions Completed: {total_sessions}
- Therapeutic Relationship Quality: {relationship_quality}
- Therapy Style: {therapy_style}

PREVIOUS SESSION DATA:
Session Transcript:
{session_transcript}

Session Analysis (from Memory Agent):
- Key Themes: {key_themes}
- Emotional State: {emotional_state}
- Insights: {insights}
- Progress Indicators: {progress_indicators}

Therapeutic Memory (Aggregated Across All Sessions):
{therapeutic_memory}

Treatment Plan Assessment (from Planning Agent):
{plan_assessment}

YOUR TASK:
Generate a complete SessionBriefing JSON object with the following structure. Each field must be carefully synthesized from the above data:

{{
  "briefing_type": "resumption",
  "generated_at": "{generated_at}",
  "session_count": {total_sessions},
  "last_session_id": "{last_session_id}",
  "last_session_date": "{last_session_date}",

  "narrative_handoff": "<REQUIRED: 3-4 sentence narrative that captures the essence of the last session. What was the emotional arc? What core themes emerged? What progress or challenges occurred? This should read like a supervisor briefing the next therapist.>",

  "patient_observations": "<REQUIRED: 2-3 sentences about HOW the patient communicated, not just WHAT they said. Note: communication style, openness level, defensiveness, engagement, any shifts in behavior or presentation compared to previous sessions.>",

  "plan_progression_notes": "<REQUIRED: 2-3 sentences assessing how this session advanced the overall treatment plan. Did it move forward as expected? Were there deviations? Is the plan still appropriate?>",

  "relationship_quality": "<One of: 'building', 'developing', 'established', 'strong'>",

  "continuity_points": [
    "<Most important topic/issue from last session that should be followed up on>",
    "<Second most important continuity point>",
    "<Additional points as needed - maximum {max_continuity_points} total>"
  ],

  "emotional_summary": {{
    "last_session": "<Emotional state during the last session>",
    "trend": "<One of: 'improving', 'stable', 'declining', 'fluctuating'>",
    "note": "<Brief note explaining the emotional progression or context>"
  }},

  "key_themes": [
    {{
      "theme": "<Theme name>",
      "status": "<One of: 'ongoing', 'newly introduced', 'underlying', 'emerging', 'resolved'>",
      "priority": "<One of: 'high', 'medium', 'low'>",
      "frequency": <number of sessions this theme has appeared>,
      "first_appearance": "<session ID>",
      "last_discussed": "<session ID>"
    }}
    // Include all relevant themes, maximum {max_key_themes}
  ],

  "progress_highlights": [
    "<Specific achievement or breakthrough from this or recent sessions>",
    "<Additional progress point>",
    // Maximum {max_progress_highlights} highlights
  ],

  "unresolved_issues": [
    "<Issue or theme that remains unaddressed or needs further exploration>",
    "<Additional unresolved issue>",
    // Maximum {max_unresolved_issues} issues
  ],

  "recommended_approach": {{
    "opening_tone": "<Warm and welcoming | Gentle and supportive | Direct and focused | Curious and exploratory>",
    "opening_focus": "<1-2 sentences: What should the therapist focus on when opening the next session?>",
    "things_to_avoid": "<1-2 sentences: What topics or approaches might not be helpful right now?>",
    "suggested_questions": [
      "<Specific open-ended question that would be good to start with>",
      "<Second suggested question>",
      "<Third suggested question - maximum {max_suggested_questions} total>"
    ],
    "therapeutic_goals_for_session": [
      "<Concrete, achievable goal for the upcoming session>",
      "<Second goal>",
      "<Third goal - maximum {max_session_goals} total>"
    ]
  }}
}}

CRITICAL REQUIREMENTS:
1. Output ONLY valid JSON - no markdown code blocks, no explanations
2. All string fields must use double quotes
3. narrative_handoff must be at least {min_narrative_length} characters and no more than {max_narrative_length}
4. patient_observations must be no more than {max_observations_length} characters
5. plan_progression_notes must be no more than {max_plan_notes_length} characters
6. At least one continuity_point and one key_theme are required
7. Use specific, concrete language - avoid vague therapeutic jargon
8. Base all analysis strictly on the provided session data
9. Ensure all enum values match exactly (case-sensitive)

Generate the complete JSON object now:
"""
