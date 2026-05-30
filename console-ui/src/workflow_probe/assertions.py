"""Milestone and leakage checks for the local workflow probe."""

from __future__ import annotations

from typing import Any


DEFAULT_FORBIDDEN = (
    "support team",
    "system artifact",
    "backend",
    "not a licensed therapist",
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
    await check("profile_created", "profile_created" in kinds)
    await check("session_started", any(e["kind"] == "ws_event" and e.get("type") == "session_started" for e in recorder.events))
    for action in criteria.get("required_actions", ["start_intake", "select_therapy_style", "continue_therapy"]):
        await check(f"workflow_action_{action}", action in actions)
    await check("therapy_style_selected", "therapy_style_selected" in kinds)
    await check("session_ended", "session_ended" in kinds)
    await check(
        "plan_update_complete",
        any(
            event["kind"] == "post_session_state"
            and event.get("workflow_state") == "plan_update_complete"
            for event in recorder.events
        ),
    )
    assistant_text = "\n".join(str(e.get("text") or "").lower() for e in recorder.events if e["kind"] == "assistant_response")
    for phrase in (*DEFAULT_FORBIDDEN, *criteria.get("forbidden_platform_phrases", [])):
        await check(f"forbidden_phrase_{phrase}", phrase.lower() not in assistant_text)
    return passed
