"""Milestone and leakage checks for the local workflow probe."""

from __future__ import annotations

import json
import re
from typing import Any


DEFAULT_FORBIDDEN = (
    "support team",
    "system artifact",
    "backend",
    "not a licensed therapist",
)
DEFAULT_RELEVANCE_TERMS = (
    "monday",
    "deadline",
    "chest",
    "failing",
    "ceiling",
    "sleep",
)
DEFAULT_CONCRETE_STEP_TERMS = (
    "notice",
    "map",
    "track",
    "breathe",
    "breath",
    "ground",
    "write",
)


async def run_assertions(recorder: Any, scenario: dict[str, Any]) -> bool:
    criteria = scenario.get("milestones", {})
    passed = True

    async def check(name: str, condition: bool, detail: str = "") -> None:
        nonlocal passed
        passed = passed and condition
        await recorder.record_assertion(name, condition, detail)

    kinds = [event["kind"] for event in recorder.events]
    actions = {
        event.get("action")
        for event in recorder.events
        if event["kind"] == "workflow_action"
    }
    first_index_by_kind = _first_index_by_kind(recorder.events)
    await check("profile_created", "profile_created" in kinds)
    await check(
        "session_started",
        any(
            e["kind"] == "ws_event" and e.get("type") == "session_started"
            for e in recorder.events
        ),
    )
    for action in criteria.get(
        "required_actions",
        ["start_intake", "select_therapy_style", "start_therapy", "continue_therapy"],
    ):
        await check(f"workflow_action_{action}", action in actions)
    await check("therapy_style_selected", "therapy_style_selected" in kinds)
    await check("session_ended", "session_ended" in kinds)
    await check(
        "session_end_state",
        any(
            event["kind"] == "session_ended"
            and _event_data(event).get("workflow_state") == "plan_update_in_progress"
            for event in recorder.events
        ),
    )
    await check(
        "plan_update_complete",
        any(
            event["kind"] == "post_session_state_summary"
            and event.get("workflow_state") == "plan_update_complete"
            for event in recorder.events
        )
        or any(
            event["kind"] in {"post_session_job_status_summary", "job_status"}
            and event.get("job_type") == "post_session_update"
            and event.get("status") == "complete"
            for event in recorder.events
        ),
    )
    rows = recorder.created_rows
    sessions = rows.get("sessions", [])
    intake_sessions = [row for row in sessions if row.get("session_type") == "intake"]
    therapy_sessions = [row for row in sessions if row.get("session_type") == "therapy"]
    await check("single_intake_session", len(intake_sessions) == 1)
    await check("single_therapy_session", len(therapy_sessions) == 1)
    intake_transcript = _transcript(intake_sessions[0]) if intake_sessions else []
    therapy_transcript = _transcript(therapy_sessions[0]) if therapy_sessions else []
    intake_user_turns = [
        item for item in intake_transcript if item.get("role") == "user"
    ]
    await check(
        "intake_minimum_patient_turns",
        len(intake_user_turns) >= int(criteria.get("minimum_intake_patient_turns", 3)),
        f"turns={len(intake_user_turns)}",
    )
    intake_assistant_text = "\n".join(
        str(item.get("content") or "").lower()
        for item in intake_transcript
        if item.get("role") == "assistant"
    )
    for phrase in ("psychoanalytic lens", "in psychoanalytic terms", "your psyche"):
        await check(f"neutral_intake_{phrase}", phrase not in intake_assistant_text)
    if "defense" in intake_assistant_text:
        await recorder.record(
            "warning",
            message="Neutral intake used broad psychoanalytic terminology",
            phrase="defense",
        )
    await check(
        "intake_risk_screen",
        "thoughts of harming yourself or someone else" in intake_assistant_text,
    )
    await check(
        "intake_goal_preference",
        "what would you most want to be different" in intake_assistant_text,
    )
    await check(
        "therapy_session_plan_linked",
        bool(therapy_sessions and therapy_sessions[0].get("plan_id")),
    )
    await check(
        "intake_session_plan_unlinked",
        bool(intake_sessions and intake_sessions[0].get("plan_id") is None),
    )
    await check(
        "assessment_recommendations_persisted",
        len(rows.get("assessment_recommendations", [])) >= 1,
    )
    await check(
        "assessment_before_style_selection",
        _event_index(
            recorder.events,
            lambda event: event["kind"] == "ws_event"
            and event.get("type") == "assessment_recommendations",
        )
        < first_index_by_kind.get("therapy_style_selected", 10**9),
    )
    await check(
        "style_selection_before_therapy_session",
        first_index_by_kind.get("therapy_style_selected", 10**9)
        < _event_index(
            recorder.events,
            lambda event: event["kind"] == "ws_event"
            and event.get("type") == "session_started"
            and _event_data(event).get("session_type") == "therapy",
        ),
    )
    profile_rows = rows.get("user_profiles", [])
    await check(
        "final_persisted_status",
        bool(profile_rows and profile_rows[0].get("status") == "PLAN_UPDATE_COMPLETE"),
    )
    plan_rows = rows.get("therapy_plans", [])
    if plan_rows:
        latest_plan = max(plan_rows, key=lambda row: int(row.get("version") or 0))
        current_plans = [
            row for row in plan_rows if row.get("superseded_by_plan_id") is None
        ]
        previous_plans = [row for row in plan_rows if row.get("superseded_by_plan_id")]
        goals = json.loads(latest_plan.get("initial_goals") or "[]")
        interventions = json.loads(latest_plan.get("planned_interventions") or "[]")
        await check("structured_initial_goals", len(goals) >= 2)
        await check("structured_planned_interventions", len(interventions) >= 2)
        await check("single_current_plan", len(current_plans) == 1)
        if len(plan_rows) > 1:
            await check(
                "therapy_plan_version_incremented",
                int(latest_plan.get("version") or 0) >= 2,
            )
            await check(
                "explicit_plan_lineage",
                bool(
                    previous_plans
                    and latest_plan.get("supersedes_plan_id")
                    == previous_plans[-1].get("plan_id")
                    and previous_plans[-1].get("superseded_by_plan_id")
                    == latest_plan.get("plan_id")
                ),
            )
        else:
            await check(
                "no_forced_plan_revision_for_short_session",
                int(latest_plan.get("version") or 0) == 1,
            )
        await check(
            "historical_session_plan_link",
            bool(
                therapy_sessions
                and therapy_sessions[0].get("plan_id")
                == (
                    previous_plans[-1].get("plan_id")
                    if previous_plans
                    else latest_plan.get("plan_id")
                )
            ),
        )
        await check(
            "separate_revision_recommendations",
            latest_plan.get("revision_recommendations") is not None,
        )
        therapy_session_briefing = (
            therapy_sessions[0].get("session_briefing") if therapy_sessions else None
        )
        await check(
            "therapy_session_briefing_persisted",
            bool(therapy_session_briefing),
        )
        await check(
            "profile_linked_to_latest_plan",
            bool(
                profile_rows
                and profile_rows[0].get("plan_id") == latest_plan.get("plan_id")
            ),
        )
        briefing = json.loads(
            therapy_session_briefing or latest_plan.get("session_briefing") or "{}"
        )
        await check(
            "briefing_intervention_evidence",
            isinstance(briefing.get("intervention_evidence"), list),
        )
    else:
        await check("therapy_plan_persisted", False)
    await check(
        "single_style_selection_effect",
        kinds.count("therapy_style_selected") == 1,
    )
    therapy_jobs = [
        row
        for row in rows.get("session_enrichment_jobs", [])
        if therapy_sessions
        and row.get("session_id") == therapy_sessions[0].get("session_id")
    ]
    await check(
        "therapy_enrichment_complete",
        bool(
            therapy_sessions
            and therapy_sessions[0].get("enriched")
            and therapy_jobs
            and all(row.get("status") == "complete" for row in therapy_jobs)
        ),
    )
    disclosure_response = _assistant_response_after_first_user(therapy_transcript)
    relevance_terms = criteria.get(
        "therapy_response_relevance_terms",
        DEFAULT_RELEVANCE_TERMS,
    )
    matched_terms = [
        term for term in relevance_terms if term.lower() in disclosure_response.lower()
    ]
    await check(
        "therapy_response_relevant",
        len(matched_terms) >= int(criteria.get("minimum_therapy_relevance_terms", 2)),
        f"matched={matched_terms}",
    )
    await check(
        "therapy_response_max_questions",
        _question_count(disclosure_response)
        <= int(criteria.get("therapy_response_max_questions", 3)),
        f"questions={_question_count(disclosure_response)}",
    )
    await check(
        "therapy_response_max_words",
        len(disclosure_response.split())
        <= int(criteria.get("therapy_response_max_words", 220)),
        f"words={len(disclosure_response.split())}",
    )
    await check(
        "therapy_response_has_concrete_next_step",
        any(
            term in disclosure_response.lower()
            for term in criteria.get(
                "therapy_response_concrete_step_terms",
                DEFAULT_CONCRETE_STEP_TERMS,
            )
        ),
    )
    await check(
        "therapy_response_no_unearned_progress_claims",
        not any(
            phrase in disclosure_response.lower()
            for phrase in ("you made progress", "you successfully", "you overcame")
        ),
    )
    await check(
        "no_repeated_therapy_opening",
        "how has your week been" not in disclosure_response.lower()
        and not disclosure_response.lower().startswith(("hello", "welcome back")),
    )
    await check(
        "therapist_transcript_role",
        any(
            item.get("agent") == "THERAPIST"
            for item in therapy_transcript
            if item.get("role") == "assistant"
        ),
    )
    await check(
        "therapy_ws_role_and_style",
        any(
            event.get("kind") == "ws_event"
            and event.get("type") == "session_started"
            and _event_data(event).get("agent_type") == "THERAPIST"
            and _event_data(event).get("selected_therapy_style") == "cbt"
            for event in recorder.events
        ),
    )
    timings = recorder._load_phase_timings()
    timing_summary = recorder._load_llm_timing_summary()
    for phase in (
        "assessment_generation_ms",
        "initial_plan_generation_ms",
        "therapy_opening_ms",
        "therapy_response_ms",
        "post_session_update_ms",
    ):
        await check(f"timing_{phase}", phase in timings)
    await check(
        "timing_total_llm_latency_present",
        timing_summary["llm_total_latency_ms"] > 0,
    )
    await check(
        "timing_no_unphased_llm_calls",
        timing_summary["llm_unphased_finish_count"] == 0,
        f"unphased={timing_summary['llm_unphased_finish_count']}",
    )
    await check(
        "timeline_renderable",
        "Workflow Timeline" in recorder._render_timeline(),
    )
    await check(
        "transcript_has_session_boundaries",
        "## Session" in recorder._render_transcript(),
    )
    assistant_text = "\n".join(
        str(e.get("text") or "").lower()
        for e in recorder.events
        if e["kind"] == "assistant_response"
    )
    for phrase in (
        *DEFAULT_FORBIDDEN,
        *criteria.get("forbidden_platform_phrases", []),
    ):
        await check(f"forbidden_phrase_{phrase}", phrase.lower() not in assistant_text)
    return passed


def _transcript(session: dict[str, Any]) -> list[dict[str, Any]]:
    transcript = session.get("transcript") or []
    if isinstance(transcript, str):
        transcript = json.loads(transcript)
    return transcript if isinstance(transcript, list) else []


def _assistant_response_after_first_user(transcript: list[dict[str, Any]]) -> str:
    saw_user = False
    for item in transcript:
        if item.get("role") == "user":
            saw_user = True
        elif saw_user and item.get("role") == "assistant":
            return str(item.get("content") or "")
    return ""


def _first_index_by_kind(events: list[dict[str, Any]]) -> dict[str, int]:
    indexes: dict[str, int] = {}
    for index, event in enumerate(events):
        indexes.setdefault(event["kind"], index)
    return indexes


def _event_index(events: list[dict[str, Any]], predicate) -> int:
    for index, event in enumerate(events):
        if predicate(event):
            return index
    return 10**9


def _event_data(event: dict[str, Any]) -> dict[str, Any]:
    data = event.get("data")
    return data if isinstance(data, dict) else {}


def _question_count(text: str) -> int:
    return len(re.findall(r"\?", text))
