"""Small helpers for durable legacy characterization assertions."""

from __future__ import annotations

import json
from typing import Any


def profile_rows(rows: list[dict]) -> list[dict]:
    return rows


def assert_single_profile(rows: list[dict]) -> dict:
    assert len(rows) == 1, f"expected one profile, found {len(rows)}"
    return rows[0]


def assert_ready_status(profile: dict) -> None:
    status = profile.get("status")
    assert status in {
        "INITIAL_PLAN_COMPLETE",
        "THERAPY_IN_PROGRESS",
        "PLAN_UPDATE_COMPLETE",
    }, f"unexpected ready-ish status: {status}"


def assert_one_intake_session(sessions: list[dict]) -> dict:
    intake_sessions = [
        row for row in sessions if row.get("session_type") == "intake"
    ]
    assert len(intake_sessions) >= 1, "expected at least one intake session"
    return intake_sessions[0]


def transcript_messages(session_row: dict) -> list[dict[str, Any]]:
    raw = session_row.get("transcript") or "[]"
    if isinstance(raw, str):
        return json.loads(raw)
    return list(raw)


def assert_ordered_roles(messages: list[dict], roles: tuple[str, ...]) -> None:
    observed = tuple(message.get("role") for message in messages if message.get("role"))
    assert observed[: len(roles)] == roles, f"unexpected message order: {observed}"


def assert_assessment_results(rows: list[dict]) -> None:
    assert len(rows) >= 1, "expected assessment recommendations to persist"


def assert_plans(rows: list[dict], minimum: int = 1) -> None:
    assert len(rows) >= minimum, f"expected at least {minimum} therapy plan(s)"


def assert_intake_evidence(session_row: dict) -> None:
    assert session_row.get("intake_record"), "expected intake evidence on session row"
