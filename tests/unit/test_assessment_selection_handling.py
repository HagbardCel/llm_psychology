from __future__ import annotations

from psychoanalyst_app.agents.assessment.selection import (
    build_continuation_choice_response,
    build_selection_pending_response,
)


def test_continuation_choice_finish_routes_to_end_session() -> None:
    response = build_continuation_choice_response("finish")
    assert response.next_action == "end_session"
    assert response.metadata["session_ended"] is True


def test_continuation_choice_continue_routes_to_start_therapy() -> None:
    response = build_continuation_choice_response("continue")
    assert response.next_action == "start_therapy"
    assert response.metadata["new_session_required"] is True


def test_continuation_choice_unknown_requests_clarification() -> None:
    response = build_continuation_choice_response("other")
    assert response.next_action == "await_continuation_choice"
    assert "option 1" in response.content


def test_selection_pending_response_uses_ui_flow_message() -> None:
    response = build_selection_pending_response("cbt")
    assert response.next_action == "await_selection"
    assert response.metadata["selected_style"] == "cbt"
