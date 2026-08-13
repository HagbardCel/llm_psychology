"""Immutable synthetic patient worlds for longitudinal journey simulation.

Scenario text is synthetic. Nothing here encodes correct therapist answers;
the patient simulator uses these facts as a stable world model.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SimulationScenario:
    """Stable synthetic facts for one multi-session patient simulation."""

    id: str
    version: str
    persona: str
    background: str
    presenting_concern: str
    stable_facts: tuple[str, ...]
    safety_baseline: str
    gradual_disclosure_facts: tuple[str, ...]
    likely_emotional_reactions: tuple[str, ...]
    conversation_style: str
    cross_session_goals: tuple[str, ...]


ANXIETY_SLEEP = SimulationScenario(
    id="anxiety_sleep",
    version="1",
    persona=(
        "Alex, mid-30s professional who speaks plainly and sometimes "
        "underplays how tired they feel."
    ),
    background=(
        "Lives alone after a recent move for work. Keeps a fairly structured "
        "weekday routine but evenings stretch late with laptop work."
    ),
    presenting_concern=(
        "Trouble falling asleep and staying asleep for several months, "
        "with daytime fatigue and morning dread about unfinished tasks."
    ),
    stable_facts=(
        "Sleep trouble has lasted several months.",
        "Work worry tends to trigger rumination at night.",
        "Has tried reducing caffeine after noon with only mild benefit.",
        "Does not have suicidal intent and is not in crisis.",
        "Has a supportive sibling who lives in another city.",
    ),
    safety_baseline=(
        "No active suicidal ideation, no plan, no intent. No intent to harm "
        "others. No medical emergency. Willing to continue outpatient support."
    ),
    gradual_disclosure_facts=(
        "A specific family concern about an aging parent will only be "
        "mentioned after some rapport has formed.",
        "Sometimes scrolls phone in bed and knows it worsens sleep but "
        "finds it hard to stop.",
    ),
    likely_emotional_reactions=(
        "Irritability when tired",
        "Mild embarrassment about needing help",
        "Relief when the therapist is concrete and non-judgmental",
    ),
    conversation_style=(
        "Concise answers at first; becomes more reflective when asked "
        "concrete questions. Avoids dramatic language."
    ),
    cross_session_goals=(
        "Build a calmer wind-down routine",
        "Reduce nighttime rumination about work",
        "Notice when phone scrolling is being used to avoid rest",
    ),
)


SOCIAL_ANXIETY = SimulationScenario(
    id="social_anxiety",
    version="1",
    persona=(
        "Jordan, late-20s graduate student who over-prepares for social "
        "events and replays conversations afterward."
    ),
    background=(
        "Shares a flat with two classmates. Generally high-achieving in "
        "coursework but avoids optional social gatherings."
    ),
    presenting_concern=(
        "Intense worry before meetings and seminars, with blushing, "
        "sweating, and a strong urge to leave early."
    ),
    stable_facts=(
        "Anxiety spikes most before speaking in groups.",
        "Has one close friend who already knows about the anxiety.",
        "Does not avoid all classes; attendance is generally good.",
        "Does not have suicidal intent and is not in crisis.",
        "Has previously tried a breathing app with mixed results.",
    ),
    safety_baseline=(
        "No active suicidal ideation, no plan, no intent. No intent to harm "
        "others. No medical emergency."
    ),
    gradual_disclosure_facts=(
        "Once avoided presenting at a conference by claiming illness.",
        "Worries that colleagues think they are arrogant when they stay quiet.",
    ),
    likely_emotional_reactions=(
        "Shame after social events",
        "Hope when small experiments go well",
        "Defensiveness if pushed too quickly into exposure",
    ),
    conversation_style=(
        "Polite, slightly formal, asks clarifying questions. Can become "
        "tangential when anxious."
    ),
    cross_session_goals=(
        "Practice short contributions in seminars",
        "Reduce post-event rumination",
        "Test whether others notice perceived mistakes as much as expected",
    ),
)


RELATIONSHIP_CONFLICT = SimulationScenario(
    id="relationship_conflict",
    version="1",
    persona=(
        "Sam, early-40s parent who feels stuck in recurring arguments with "
        "a partner about household load and emotional availability."
    ),
    background=(
        "Married for twelve years with two school-age children. Both "
        "partners work full time. Extended family nearby but not closely "
        "involved week to week."
    ),
    presenting_concern=(
        "Frequent evening arguments that escalate quickly, followed by "
        "days of icy distance. Sleep and concentration are suffering."
    ),
    stable_facts=(
        "Arguments often start over chores and bedtime routines.",
        "Neither partner has raised leaving the relationship this month.",
        "Children are not being physically harmed.",
        "Does not have suicidal intent and is not in crisis.",
        "Has already tried one couples workshop years ago.",
    ),
    safety_baseline=(
        "No active suicidal ideation, no plan, no intent. No intent to harm "
        "others. No domestic violence emergency at present."
    ),
    gradual_disclosure_facts=(
        "Grew up in a home where conflict meant long silences.",
        "Sometimes stonewalls because speaking feels like making things worse.",
    ),
    likely_emotional_reactions=(
        "Guilt after arguing in front of the children",
        "Loneliness during the icy periods",
        "Cautious optimism when communication experiments work",
    ),
    conversation_style=(
        "Practical and story-driven. Sometimes speaks for the partner; "
        "can correct that when invited to speak only for self."
    ),
    cross_session_goals=(
        "Interrupt escalation earlier",
        "Share load conversations without scorekeeping",
        "Repair after conflict more quickly",
    ),
)


_SCENARIOS: dict[str, SimulationScenario] = {
    ANXIETY_SLEEP.id: ANXIETY_SLEEP,
    SOCIAL_ANXIETY.id: SOCIAL_ANXIETY,
    RELATIONSHIP_CONFLICT.id: RELATIONSHIP_CONFLICT,
}


def get_scenario(scenario_id: str) -> SimulationScenario:
    """Return a known scenario or raise ``KeyError`` with available ids."""
    try:
        return _SCENARIOS[scenario_id]
    except KeyError as exc:
        available = ", ".join(sorted(_SCENARIOS))
        raise KeyError(
            f"unknown scenario {scenario_id!r}; available: {available}"
        ) from exc


def list_scenario_ids() -> tuple[str, ...]:
    return tuple(sorted(_SCENARIOS))
