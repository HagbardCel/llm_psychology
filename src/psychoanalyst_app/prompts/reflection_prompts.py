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

Current Treatment Trajectory (Tier 4 fields on TherapyPlan):
- Initial Goals: {tier4_initial_goals}
- Current Progress: {tier4_current_progress}
- Planned Interventions: {tier4_planned_interventions}
- Status: {tier4_status}

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
  }},

  "tier4_update": {{
    "should_update": <true|false>,
    "current_progress": "<If should_update=true: updated qualitative progress summary. If false: repeat current progress verbatim.>",
    "planned_interventions": [
      "<If should_update=true: updated list of planned interventions. If false: repeat the current list.>"
    ],
    "status": "<One of: 'active', 'paused', 'completed'>",
    "rationale": "<1-2 sentences explaining why an update is or isn't needed>"
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

# Tier 2 session enrichment prompt
TIER2_ENRICHMENT_PROMPT = """
Analyze the following therapy session transcript and extract clinical \
psychological data.

SESSION TRANSCRIPT:
{session_transcript}

TASK:
Extract psychological and clinical information from this session into \
structured JSON format.
Focus on observable clinical phenomena, affective states, and therapeutic \
dynamics.

Extract the following:

1. PSYCHOLOGICAL_SUMMARY (2-3 paragraphs, max 3000 chars):
   - Synthesize the clinical content of the session
   - What were the central concerns and discussions?
   - What psychological processes were observable?
   - What was the overall trajectory of the session?

2. DOMINANT_AFFECTS (list of strings):
   - Primary emotional states observed during the session
   - Use specific affect names: anxiety, sadness, anger, fear, shame, guilt, joy, etc.
   - List 2-5 most prominent affects in order of salience

3. KEY_THEMES (list of strings):
   - Major psychological themes and concerns discussed
   - Examples: "work-related stress", "relationship conflict", "grief about father"
   - List 2-6 key themes

4. NOTABLE_INTERACTIONS (string, max 1500 chars, or null):
   - Significant transference or countertransference moments
   - Moments of resistance or defensiveness
   - Ruptures or repairs in therapeutic relationship
   - Notable shifts in patient's engagement or openness
   - Use null if no particularly notable interactions occurred

5. INTERPRETATIONS (string, max 1000 chars, or null):
   - Key interpretations or insights offered by the therapist
   - Links made between present and past
   - Patterns identified
   - Use null if no explicit interpretations were offered

6. PATIENT_REACTIONS (string, max 1000 chars, or null):
   - How the patient responded to interventions
   - Moments of insight or recognition
   - Defensive responses or rejections
   - Emotional shifts following interventions
   - Use null if no significant reactions to note

IMPORTANT GUIDELINES:
- Extract ONLY information present in the transcript
- Be clinically precise - avoid vague therapeutic jargon
- Focus on observable phenomena, not speculation
- Preserve the clinical significance of moments
- Use professional psychological language
- If a field has no meaningful content, use null (not empty string)

Return the data as JSON with this exact structure:
{{
  "psychological_summary": "string (2-3 paragraphs)",
  "dominant_affects": ["affect1", "affect2", "affect3"],
  "key_themes": ["theme1", "theme2", "theme3"],
  "notable_interactions": "string or null",
  "interpretations": "string or null",
  "patient_reactions": "string or null"
}}
"""

# Tier 3 change detection prompt
TIER3_CHANGE_DETECTION_PROMPT = """
Evaluate whether the clinical formulation (Tier 3) should be updated based \
on this therapy session.

CURRENT CLINICAL FORMULATION (Version {current_version}):
{current_analysis}

LATEST SESSION SUMMARY:
{session_summary}

TASK:
Determine if this session contains new information that would meaningfully \
change the clinical formulation.

Consider whether there are:
1. **Shifts in central theme**: Has the main therapeutic focus changed?
2. **New transference patterns**: Are there new transference dynamics?
3. **Emerging narratives**: New recurring stories or themes appearing?
4. **Changes in defenses**: Shifts in defensive organization or flexibility?
5. **Modified clinical stance**: Need to adjust pacing, risk areas, or \
key questions?

DECISION CRITERIA:
- **UPDATE**: If there are significant shifts in clinical understanding \
(~30-50% of sessions)
- **NO UPDATE**: If the session confirms existing formulation without \
substantial change

Return JSON with this structure:
{{
  "update_needed": true or false,
  "change_summary": "Brief explanation of what changed (if update_needed=true) \
or null",
  "confidence": "high" or "medium" or "low"
}}

IMPORTANT:
- Be conservative - only update when there's meaningful clinical change
- Prefer "no update" if session reinforces existing understanding
- change_summary should be 1-2 sentences explaining what shifted
"""

# Tier 3 update generation prompt
TIER3_UPDATE_GENERATION_PROMPT = """
Generate an updated clinical formulation (Tier 3) based on new session data.

CURRENT FORMULATION (Version {current_version}):
{current_analysis}

LATEST SESSION SUMMARY:
{session_summary}

CHANGE RATIONALE:
{change_summary}

TASK:
Create an UPDATED clinical formulation that incorporates insights from \
the latest session.

Build on the previous version while integrating new understanding.

Extract the following into structured JSON format:

1. CURRENT FOCUS:
   - theme (string, max 200 chars): Central theme or concern
   - salience (string, max 500 chars): Why this theme is salient now

2. TRANSFERENCE IMPRESSIONS:
   - idealization (string, max 500 chars, or null): Idealizing transference
   - devaluation (string, max 500 chars, or null): Devaluing transference
   - boundaries (string, max 500 chars, or null): Boundary dynamics
   - other_patterns (string, max 1000 chars, or null): Other transference \
patterns

3. RECURRING NARRATIVES (list of objects):
   - title (string, max 100 chars): Short label
   - description (string, max 1000 chars): Description and significance
   - first_appeared (string): Session ID or "intake"

   Include ALL narratives (carry forward + new ones)

4. DEFENSIVE ORGANIZATION:
   - primary_defenses (list of strings): Main defense mechanisms
   - defensive_style (string, max 500 chars, or null): Overall organization
   - flexibility (string, max 300 chars, or null): Rigidity vs flexibility

5. ANALYTIC ORIENTATION:
   - pacing (string, max 300 chars, or null): Recommended pace
   - risk_areas (list of strings): Areas requiring caution
   - key_questions (list of strings): Important questions to explore

IMPORTANT GUIDELINES:
- Maintain continuity with previous version
- Integrate new insights while preserving core understanding
- Update fields that changed, carry forward unchanged elements
- Be clinically precise and evidence-based

Return the data as JSON with this exact structure:
{{
  "current_focus": {{
    "theme": "string",
    "salience": "string"
  }},
  "transference": {{
    "idealization": "string or null",
    "devaluation": "string or null",
    "boundaries": "string or null",
    "other_patterns": "string or null"
  }},
  "narratives": [
    {{
      "title": "string",
      "description": "string",
      "first_appeared": "string"
    }}
  ],
  "defenses": {{
    "primary_defenses": ["defense1", "defense2"],
    "defensive_style": "string or null",
    "flexibility": "string or null"
  }},
  "orientation": {{
    "pacing": "string or null",
    "risk_areas": ["risk1", "risk2"],
    "key_questions": ["question1", "question2"]
  }}
}}
"""

# Tier 1 change detection prompt
TIER1_CHANGE_DETECTION_PROMPT = """
Evaluate whether the patient background profile (Tier 1) should be updated based on the latest session.

CURRENT PATIENT PROFILE (Tier 1 JSON):
{current_profile_json}

LATEST SESSION SUMMARY:
{session_summary}

TASK:
Determine if the patient explicitly stated new or corrected background information that should update Tier 1.

Update only if the patient provided clear factual information (not speculation).

Return JSON with this structure:
{{
  "update_needed": true or false,
  "change_summary": "1-2 sentences (if update_needed=true) or null",
  "confidence": "high" or "medium" or "low"
}}

IMPORTANT:
- Be conservative and factual
- Do not infer missing details
"""

# Tier 1 update generation prompt
TIER1_UPDATE_GENERATION_PROMPT = """
Generate an updated Tier 1 patient profile PATCH based on new factual information from the latest session.

CURRENT PATIENT PROFILE (Tier 1 JSON):
{current_profile_json}

LATEST SESSION SUMMARY:
{session_summary}

CHANGE RATIONALE:
{change_summary}

TASK:
Return ONLY the fields that should be updated, using the same nested keys as the Tier 1 profile schema:
- basic_info
- family
- history
- context
- frame

Use null for fields you are not updating. Do not include user_id/created_at/updated_at.

Return JSON with this structure:
{{
  "basic_info": {{ "alias": null, "data_of_birth": null, "gender": null, "cultural_background": null, "primary_language": null }},
  "family": {{ "parents": null, "siblings": null, "family_atmosphere": null, "significant_events": null }},
  "history": {{ "education": null, "work_history": null, "relationship_to_work": null }},
  "context": {{ "relationships": null, "social_context": null, "current_situation": null }},
  "frame": {{ "preferred_school": null, "boundary_notes": null, "frame_notes": null }}
}}

IMPORTANT:
- Update only factual information explicitly stated by the patient
- Do not invent data; keep unchanged fields null
"""
