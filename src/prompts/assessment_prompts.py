"""
Assessment prompts for therapy style selection and initial formulation.

This module contains prompts for:
- Tier 3: Initial clinical formulation (PatientAnalysis v1)
- Tier 4: Initial therapy plan (TherapyPlan)
"""

# Tier 3: Initial Clinical Formulation Extraction
TIER3_INITIAL_FORMULATION_PROMPT = """
Based on the intake assessment below, create an initial clinical formulation.

PATIENT BACKGROUND (Tier 1):
{patient_background}

INTAKE SESSION:
{intake_transcript}

SELECTED THERAPY STYLE: {therapy_style}

TASK:
Create an initial clinical formulation (Tier 3: PatientAnalysis) that will \
guide the therapeutic work. This is version 1 - your first clinical \
understanding of this patient.

Extract the following into structured JSON format:

1. CURRENT FOCUS:
   - theme (string, max 200 chars): Central theme or concern to address
   - salience (string, max 500 chars): Why this theme is most salient now

2. TRANSFERENCE IMPRESSIONS:
   - idealization (string, max 500 chars, or null): Early signs of \
idealizing transference
   - devaluation (string, max 500 chars, or null): Early signs of \
devaluing transference
   - boundaries (string, max 500 chars, or null): Boundary testing or \
concerns observed
   - other_patterns (string, max 1000 chars, or null): Other notable \
transference dynamics

3. RECURRING NARRATIVES (list of objects):
   - title (string, max 100 chars): Short label for this narrative
   - description (string, max 1000 chars): Description and its significance
   - first_appeared (string, or null): When first emerged (e.g., "intake" \
or session ID)

   Include 1-3 key narratives that emerged during intake.

4. DEFENSIVE ORGANIZATION:
   - primary_defenses (list of strings): Main defense mechanisms observed \
(e.g., "intellectualization", "projection", "denial")
   - defensive_style (string, max 500 chars, or null): Overall defensive \
organization
   - flexibility (string, max 300 chars, or null): Rigidity vs flexibility \
of defenses

5. ANALYTIC ORIENTATION:
   - pacing (string, max 300 chars, or null): Recommended pace of \
intervention
   - risk_areas (list of strings): Areas requiring caution
   - key_questions (list of strings): Important questions to explore

IMPORTANT GUIDELINES:
- Extract ONLY information observable from intake
- Be clinically precise and evidence-based
- Use professional psychological language
- This is an INITIAL formulation - expect it to evolve
- Focus on what's therapeutically relevant
- Use null for fields without clear evidence

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
      "first_appeared": "intake"
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

# Tier 4: Initial Therapy Plan Extraction
TIER4_INITIAL_PLAN_PROMPT = """
Based on the intake assessment and initial formulation, create an initial \
treatment plan.

PATIENT BACKGROUND (Tier 1):
{patient_background}

INTAKE SESSION:
{intake_transcript}

SELECTED THERAPY STYLE: {therapy_style}

CLINICAL FORMULATION (Tier 3):
{clinical_formulation}

TASK:
Create an initial treatment plan (Tier 4: TherapyPlan) that defines \
therapeutic goals and intervention strategy.

Extract the following into structured JSON format:

1. INITIAL_GOALS (list of strings, minimum 1 required):
   - Concrete therapeutic goals identified during assessment
   - Should be specific, meaningful, and clinically appropriate
   - Examples: "Reduce work-related anxiety", "Explore childhood trauma", \
"Improve interpersonal relationships"
   - Include 2-5 goals

2. CURRENT_PROGRESS (string, max 2000 chars):
   - Qualitative assessment of where patient is starting from
   - Baseline functioning and presenting concerns
   - Patient's readiness and motivation for therapy
   - Any initial positive signs or concerns

   This is the BASELINE - describe the starting point.

3. PLANNED_INTERVENTIONS (list of strings):
   - Planned therapeutic interventions or directions
   - Should align with selected therapy style
   - Examples: "Free association exploration", "Dream analysis", \
"Cognitive restructuring", "Transference interpretation"
   - Include 2-4 planned interventions

4. STATUS (string): Must be "active" (this is a new plan)

IMPORTANT GUIDELINES:
- Goals should be drawn from patient's stated concerns and intake discussion
- Progress description is the BASELINE snapshot
- Interventions should match the {therapy_style} approach
- Be realistic and clinically appropriate
- This plan will be updated periodically as therapy progresses

Return the data as JSON with this exact structure:
{{
  "initial_goals": [
    "goal1",
    "goal2",
    "goal3"
  ],
  "current_progress": "Baseline description of patient's current state...",
  "planned_interventions": [
    "intervention1",
    "intervention2"
  ],
  "status": "active"
}}
"""
