# AI Analyst Patient File Structure (Local, Qualitative, Single-User)

This document defines the internal patient file used by a locally running AI analyst for a *single user*. It is designed to support continuity, depth, and psychological realism rather than administration, compliance, or multi-user safety.

The file should be readable, editable, and interpretable by a human. All entries represent **working impressions**, not objective facts.

---

## File Structure Overview

The patient file is divided into three tiers based on how frequently the information changes and how it is used by the analyst.

- **Tier 1**: Analytic frame & background (low volatility)
- **Tier 2**: Session history (medium volatility)
- **Tier 3**: Working hypotheses & dynamic impressions (high volatility)

---

## Tier 1: Analytic Frame & Background (Low Volatility)

This section contains relatively stable information that helps the analyst understand *who the patient is*, *where they come from*, and *under which analytic frame the work takes place*.

### Basic Patient Background

- **alias**  
  Name or identifier used within the analysis. May be real or symbolic.

- **year_of_birth**  
  Approximate year of birth.

- **gender_identity**  
  Gender as described by the patient, if relevant to their narratives.

- **cultural_context**  
  Cultural, national, or regional background insofar as it shapes references, values, or expectations.

- **primary_language**  
  Language in which the patient naturally expresses emotional nuance.

---

### Family Constellation

Narrative description rather than a fixed schema.

- **parents**  
  Brief descriptions of mother and father (or caregivers): emotional availability, dominance, absence, illness, idealization, conflict patterns.

- **siblings**  
  Number, relative age, emotional roles (e.g. "the successful one", "the fragile one").

- **early_family_atmosphere**  
  Overall emotional climate growing up (e.g. tense, achievement-focused, chaotic, emotionally distant).

- **significant_family_events**  
  Losses, separations, migrations, illnesses, or ruptures frequently referenced by the patient.

---

### Educational & Work History

Used to contextualize competence, authority, shame, ambition, and identity themes.

- **educational_background**  
  Level of education, field(s) of study, interruptions, failures, or notable achievements.

- **work_history**  
  Main career trajectory, current occupation, periods of instability or burnout.

- **relationship_to_work**  
  How the patient emotionally relates to work (e.g. source of worth, avoidance of intimacy, chronic pressure).

---

### Relational & Life Context

- **romantic_relationships**  
  Patterns across relationships (e.g. avoidance, idealization, dependency, repetition of loss).

- **friendships & social life**  
  Degree of closeness, stability, conflict, or isolation.

- **current_life_situation**  
  Living situation, major stressors, transitions, or crises.

---

### Analytic Frame

Defines *how* the AI analyst is meant to work.

- **therapeutic_school**  
  Freudian, Jungian, CBT, ACT, etc.

- **analytic_mode**  
  Exploratory, interpretive, supportive, confrontational.

- **boundary_style**  
  Strict or flexible (affects how explicitly the AI comments on itself, limits, or the frame).

- **stance_notes**  
  Free-text notes on tone preferences, pacing, or sensitivities (e.g. "interpretations too early provoke withdrawal").

---

## Tier 2: Session History (Medium Volatility)

Each session is treated as a meaningful unit of psychological material, remembered for *themes and shifts*, not for metrics.

### Session Entry Structure

- **session_id**  
  Incremental identifier.

- **date**  
  Date of the session.

- **session_summary**  
  Short narrative summary of what stood out psychologically.

- **dominant_affects**  
  Emotions that were particularly present or notable.

- **key_themes_or_images**  
  Recurring metaphors, dreams, images, or stories.

- **notable_interactions**  
  Moments of tension, silence, anger, closeness, confusion, or rupture in the analytic relationship.

- **interpretations_or_interventions**  
  Interpretations offered, questions posed, or shifts in stance.

- **patient_reactions**  
  Immediate or delayed responses to interventions (acceptance, resistance, confusion, relief).

---

## Tier 3: Working Hypotheses & Dynamic Impressions (High Volatility)

This section represents the analyst’s *current understanding*, always provisional and revisable. These entries guide tone and focus but must never be treated as facts.

### Current Focus

- **central_theme**  
  The conflict, pattern, or question currently in the foreground (e.g. abandonment, control, guilt, dependency).

- **why_it_is_salient_now**  
  Short explanation grounded in recent sessions.

---

### Transference & Relational Impressions

- **idealization_impression**  
  Qualitative description of whether the analyst is being experienced as unusually understanding, special, rescuing, or uniquely attuned.

- **distance_or_devaluation_impression**  
  Notes on withdrawal, skepticism, irritation, or dismissal toward the analyst.

- **boundary_pressure**  
  Whether the patient seems to push, test, or ignore the analytic frame.

---

### Recurring Narratives

- **repeated_storylines**  
  Descriptions of stories or complaints that recur across sessions.

- **emotional_function**  
  What these narratives seem to *do* for the patient (e.g. protect from anger, preserve self-image, avoid mourning).

---

### Defensive Organization (Impressionistic)

- **prominent_defenses**  
  Defenses that frequently appear (e.g. intellectualization, humor, minimization), described in plain language.

- **when_they_intensify**  
  Situations or topics that strengthen these defenses.

---

### Analyst Orientation Notes

- **current_pacing**  
  Whether work should slow down, deepen, or remain supportive.

- **interpretive_risk**  
  Sense of how much interpretation the patient can currently tolerate.

- **open_questions**  
  Unresolved hypotheses the analyst is holding without forcing closure.

---

## General Principle

This file is not a diagnostic instrument. It is a **living memory** of an analytic relationship, meant to support continuity, nuance, and restraint.

Everything within it may be wrong — and must remain open to revision.

