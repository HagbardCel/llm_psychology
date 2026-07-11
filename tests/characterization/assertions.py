"""Small helpers for durable legacy characterization assertions."""

from __future__ import annotations

import json
from typing import Any


def profile_rows(rows: list[dict]) -> list[dict]:
    return rows


def assert_single_profile(rows: list[dict]) -> dict:
    assert len(rows) == 1, f"expected one profile, found {len(rows)}"
    return rows[0]


def assert_profile_status(profile: dict, expected: str) -> None:
    status = profile.get("status")
    assert status == expected, f"expected profile status {expected!r}, got {status!r}"


def assert_ready_status(profile: dict) -> None:
    """Restart checkpoints after onboarding may be in therapy or post-session."""
    status = profile.get("status")
    assert status in {
        "INITIAL_PLAN_COMPLETE",
        "THERAPY_IN_PROGRESS",
        "PLAN_UPDATE_COMPLETE",
    }, f"unexpected ready-ish status: {status}"


def intake_sessions(sessions: list[dict]) -> list[dict]:
    return [row for row in sessions if row.get("session_type") == "intake"]


def assert_one_intake_session(sessions: list[dict]) -> dict:
    rows = intake_sessions(sessions)
    assert len(rows) == 1, f"expected exactly one intake session, found {len(rows)}"
    return rows[0]


def assert_exactly_n_intake_sessions(sessions: list[dict], count: int) -> list[dict]:
    rows = intake_sessions(sessions)
    assert len(rows) == count, (
        f"expected exactly {count} intake session(s), found {len(rows)}"
    )
    return rows


def transcript_messages(session_row: dict) -> list[dict[str, Any]]:
    raw = session_row.get("transcript") or "[]"
    if isinstance(raw, str):
        return json.loads(raw)
    return list(raw)


def assert_ordered_roles(messages: list[dict], roles: tuple[str, ...]) -> None:
    observed = tuple(message.get("role") for message in messages if message.get("role"))
    assert observed[: len(roles)] == roles, f"unexpected message order: {observed}"


def assert_exactly_one_assessment(rows: list[dict]) -> dict:
    assert len(rows) == 1, f"expected exactly one assessment result, found {len(rows)}"
    return rows[0]


def assert_assessment_results(rows: list[dict]) -> None:
    assert_exactly_one_assessment(rows)


def assert_exactly_one_initial_plan(rows: list[dict]) -> dict:
    assert len(rows) == 1, f"expected exactly one therapy plan, found {len(rows)}"
    return rows[0]


def assert_plans(rows: list[dict], minimum: int = 1) -> None:
    assert len(rows) >= minimum, f"expected at least {minimum} therapy plan(s)"


def assert_plan_style(plan: dict, style_id: str) -> None:
    assert plan.get("selected_therapy_style") == style_id, (
        f"expected plan style {style_id!r}, got {plan.get('selected_therapy_style')!r}"
    )


def assert_plan_belongs_to_profile(plan: dict, profile: dict) -> None:
    assert plan.get("user_id") == profile.get("user_id"), (
        "plan user_id does not match profile"
    )
    profile_plan_id = profile.get("plan_id")
    if profile_plan_id:
        assert plan.get("plan_id") == profile_plan_id, (
            "profile plan_id does not point at the plan row"
        )


def current_plan_for_user(plans: list[dict], user_id: str) -> dict:
    user_plans = [row for row in plans if row.get("user_id") == user_id]
    assert user_plans, f"no therapy plans for user {user_id!r}"
    return max(user_plans, key=lambda row: row.get("version", 0))


def assert_intake_evidence(session_row: dict) -> None:
    assert session_row.get("intake_record"), "expected intake evidence on session row"


def assert_therapy_session_closed(session_row: dict) -> None:
    assert session_row.get("session_summary"), (
        "expected session_summary on closed therapy session"
    )


def assert_plan_revision_link(old_plan: dict, new_plan: dict) -> None:
    assert new_plan.get("supersedes_plan_id") == old_plan.get("plan_id"), (
        "new plan does not supersede the prior revision"
    )
    assert old_plan.get("superseded_by_plan_id") == new_plan.get("plan_id"), (
        "prior plan is not linked to the new revision"
    )
